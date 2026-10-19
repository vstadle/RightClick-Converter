// QuickConvertMenu.dll : le sous-menu « Convertir en » du menu principal de Windows 11.
//
// Windows 11 n'affiche dans son premier menu que les commandes IExplorerCommand déclarées
// par un paquet MSIX. `quickconvert install-win11` crée ce paquet (« sparse » : une
// identité signée, sans fichiers) et dépose cette DLL dans windows11\bin\external avec
// menu.txt, la liste des formats calculée par platforms/windows.py.
//
// La DLL ne convertit rien : l'Explorateur lui passe toute la sélection d'un coup
// (IShellItemArray) et elle lance UN seul pythonw.exe avec tous les fichiers concernés.
//
// menu.txt (UTF-8, champs séparés par des tabulations) :
//     title   <libellé du menu>
//     icon    <chemin de l'icône>
//     item    <libellé>   <commande, sans les fichiers>   <extensions acceptées, séparées par des espaces>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <shobjidl.h>
#include <new>
#include <memory>
#include <string>
#include <utility>
#include <vector>

static HMODULE g_module;
static LONG g_locks;  // objets vivants + LockServer, pour DllCanUnloadNow

// Repris dans AppxManifest.xml (platforms/windows11.py).
static const CLSID CLSID_QuickConvertMenu = {0x8d81aa34, 0x5215, 0x40f5, {0x94, 0x70, 0xfb, 0xe3, 0x5a, 0x5f, 0xd6, 0x02}};

// Au-delà, la liste des fichiers passe par un fichier temporaire (limite Windows : 32 767).
static const size_t MAX_COMMAND_LINE = 30000;

struct MenuItem {
    std::wstring label;
    std::wstring command;
    std::vector<std::wstring> exts;  // en minuscules, avec le point
};

struct Menu {
    std::wstring title;
    std::wstring icon;
    std::vector<MenuItem> items;
};

using MenuPtr = std::shared_ptr<const Menu>;

static std::wstring lower(std::wstring s) {
    if (!s.empty()) CharLowerBuffW(&s[0], static_cast<DWORD>(s.size()));
    return s;
}

static std::vector<std::wstring> split(const std::wstring& s, wchar_t sep) {
    std::vector<std::wstring> parts;
    size_t start = 0;
    for (;;) {
        size_t end = s.find(sep, start);
        parts.push_back(s.substr(start, end - start));
        if (end == std::wstring::npos) return parts;
        start = end + 1;
    }
}

static std::wstring module_dir() {
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(g_module, path, MAX_PATH);
    if (n == 0 || n == MAX_PATH) return L"";
    PathRemoveFileSpecW(path);
    return path;
}

static bool read_utf8(const std::wstring& path, std::wstring& text) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    std::string bytes;
    LARGE_INTEGER size;
    DWORD read = 0;
    if (GetFileSizeEx(file, &size) && size.QuadPart > 0 && size.QuadPart < (1 << 20)) {
        bytes.resize(static_cast<size_t>(size.QuadPart));
        if (!ReadFile(file, &bytes[0], static_cast<DWORD>(bytes.size()), &read, nullptr)) read = 0;
    }
    CloseHandle(file);
    bytes.resize(read);
    int n = MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
    text.assign(n, L'\0');
    if (n) MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), &text[0], n);
    if (!text.empty() && text[0] == 0xFEFF) text.erase(0, 1);  // BOM éventuel
    return true;
}

// Relu à chaque ouverture du menu : un nouvel `install-win11` (formats ajoutés, dossier
// déplacé) est pris en compte sans redémarrer l'Explorateur.
static MenuPtr load_menu() {
    std::wstring text;
    if (!read_utf8(module_dir() + L"\\menu.txt", text)) return nullptr;
    auto menu = std::make_shared<Menu>();
    for (std::wstring& line : split(text, L'\n')) {
        if (!line.empty() && line.back() == L'\r') line.pop_back();
        std::vector<std::wstring> f = split(line, L'\t');
        if (f.size() == 2 && f[0] == L"title") {
            menu->title = f[1];
        } else if (f.size() == 2 && f[0] == L"icon") {
            menu->icon = f[1];
        } else if (f.size() == 4 && f[0] == L"item") {
            MenuItem item{f[1], f[2], {}};
            for (const std::wstring& ext : split(f[3], L' '))
                if (!ext.empty()) item.exts.push_back(lower(ext));
            menu->items.push_back(std::move(item));
        }
    }
    if (menu->items.empty()) return nullptr;
    if (menu->title.empty()) menu->title = L"QuickConvert";
    return menu;
}

static bool accepts(const MenuItem& item, const wchar_t* path) {
    std::wstring ext = lower(PathFindExtensionW(path));
    for (const std::wstring& e : item.exts)
        if (e == ext) return true;
    return false;
}

// Chemins des éléments sélectionnés que `item` sait convertir (fichiers du disque seulement).
// `first_only` : on veut juste savoir s'il y en a au moins un.
static std::vector<std::wstring> accepted_paths(IShellItemArray* items, const MenuItem& item, bool first_only) {
    std::vector<std::wstring> paths;
    DWORD count = 0;
    if (!items || FAILED(items->GetCount(&count))) return paths;
    for (DWORD i = 0; i < count; i++) {
        IShellItem* shell_item = nullptr;
        if (FAILED(items->GetItemAt(i, &shell_item))) continue;
        PWSTR path = nullptr;
        if (SUCCEEDED(shell_item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
            if (accepts(item, path)) paths.emplace_back(path);
            CoTaskMemFree(path);
        }
        shell_item->Release();
        if (first_only && !paths.empty()) break;
    }
    return paths;
}

static void append_quoted(std::wstring& command, const std::wstring& arg) {
    // Un chemin Windows ne contient ni guillemet ni barre oblique inverse finale (fichier).
    command += L" \"";
    command += arg;
    command += L'"';
}

// Écrit les chemins dans un fichier temporaire UTF-8, que Python supprime après lecture.
static std::wstring write_list_file(const std::vector<std::wstring>& paths) {
    wchar_t dir[MAX_PATH], name[MAX_PATH];
    if (!GetTempPathW(MAX_PATH, dir) || !GetTempFileNameW(dir, L"qc", 0, name)) return L"";
    std::wstring text;
    for (const std::wstring& p : paths) {
        text += p;
        text += L'\n';
    }
    int n = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    std::string bytes(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), &bytes[0], n, nullptr, nullptr);
    HANDLE file = CreateFileW(name, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_TEMPORARY, nullptr);
    if (file == INVALID_HANDLE_VALUE) return L"";
    DWORD written = 0;
    BOOL ok = WriteFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr);
    CloseHandle(file);
    if (!ok || written != bytes.size()) {
        DeleteFileW(name);
        return L"";
    }
    return name;
}

static HRESULT launch(const MenuItem& item, const std::vector<std::wstring>& paths) {
    std::wstring command = item.command;
    size_t length = command.size();
    for (const std::wstring& p : paths) length += p.size() + 3;
    if (length < MAX_COMMAND_LINE) {
        for (const std::wstring& p : paths) append_quoted(command, p);
    } else {
        std::wstring list = write_list_file(paths);
        if (list.empty()) return E_FAIL;
        command += L" --list-file";
        append_quoted(command, list);
    }

    STARTUPINFOW si = {};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {};
    std::wstring cwd = module_dir();  // pas le dossier des images : il resterait « utilisé »
    if (!CreateProcessW(nullptr, &command[0], nullptr, nullptr, FALSE, 0, nullptr,
                        cwd.empty() ? nullptr : cwd.c_str(), &si, &pi)) {
        DWORD error = GetLastError();
        std::wstring text = L"Impossible de lancer QuickConvert (erreur " + std::to_wstring(error) +
                            L").\n\nLe dossier de QuickConvert a peut-être été déplacé : relancer "
                            L"installer-win11.bat.\n\nCommande : " + item.command;
        MessageBoxW(nullptr, text.c_str(), L"QuickConvert", MB_OK | MB_ICONWARNING);
        return HRESULT_FROM_WIN32(error);
    }
    AllowSetForegroundWindow(pi.dwProcessId);  // la fenêtre de progression peut passer devant
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return S_OK;
}

// --- Commandes ---------------------------------------------------------------------------

class SubCommands;

// La commande racine « Convertir en » (index < 0) ou l'une de ses sous-commandes « PNG »...
class Command final : public IExplorerCommand {
  public:
    Command(MenuPtr menu, int index) : menu_(std::move(menu)), index_(index) { InterlockedIncrement(&g_locks); }

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == IID_IUnknown || riid == __uuidof(IExplorerCommand)) {
            *ppv = static_cast<IExplorerCommand*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    STDMETHODIMP_(ULONG) Release() override {
        LONG n = InterlockedDecrement(&refs_);
        if (n == 0) delete this;
        return n;
    }

    STDMETHODIMP GetTitle(IShellItemArray*, LPWSTR* name) override {
        *name = nullptr;
        if (!menu_) return E_FAIL;
        return SHStrDupW(root() ? menu_->title.c_str() : item().label.c_str(), name);
    }
    STDMETHODIMP GetIcon(IShellItemArray*, LPWSTR* icon) override {
        *icon = nullptr;
        if (!root() || !menu_ || menu_->icon.empty()) return E_NOTIMPL;
        return SHStrDupW(menu_->icon.c_str(), icon);
    }
    STDMETHODIMP GetToolTip(IShellItemArray*, LPWSTR* tip) override {
        *tip = nullptr;
        return E_NOTIMPL;
    }
    STDMETHODIMP GetCanonicalName(GUID* guid) override {
        *guid = root() ? CLSID_QuickConvertMenu : GUID_NULL;
        return S_OK;
    }
    STDMETHODIMP GetState(IShellItemArray* items, BOOL, EXPCMDSTATE* state) override {
        if (root()) menu_ = load_menu();
        *state = visible(items) ? ECS_ENABLED : ECS_HIDDEN;
        return S_OK;
    }
    STDMETHODIMP Invoke(IShellItemArray* items, IBindCtx*) override {
        if (root() || !menu_) return E_NOTIMPL;
        std::vector<std::wstring> paths = accepted_paths(items, item(), false);
        return paths.empty() ? S_OK : launch(item(), paths);
    }
    STDMETHODIMP GetFlags(EXPCMDFLAGS* flags) override {
        *flags = root() ? ECF_HASSUBCOMMANDS : ECF_DEFAULT;
        return S_OK;
    }
    STDMETHODIMP EnumSubCommands(IEnumExplorerCommand** commands) override;

  private:
    ~Command() { InterlockedDecrement(&g_locks); }
    bool root() const { return index_ < 0; }
    const MenuItem& item() const { return menu_->items[index_]; }

    // Racine : au moins un fichier convertible ; sous-commande : au moins un fichier
    // convertible vers ce format (pas de « JPG » pour une sélection de .jpg).
    bool visible(IShellItemArray* items) const {
        if (!menu_) return false;
        if (!root()) return !accepted_paths(items, item(), true).empty();
        for (const MenuItem& i : menu_->items)
            if (!accepted_paths(items, i, true).empty()) return true;
        return false;
    }

    LONG refs_ = 1;
    MenuPtr menu_;
    int index_;
};

class SubCommands final : public IEnumExplorerCommand {
  public:
    explicit SubCommands(MenuPtr menu, ULONG pos = 0) : menu_(std::move(menu)), pos_(pos) {
        InterlockedIncrement(&g_locks);
    }

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == IID_IUnknown || riid == __uuidof(IEnumExplorerCommand)) {
            *ppv = static_cast<IEnumExplorerCommand*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    STDMETHODIMP_(ULONG) Release() override {
        LONG n = InterlockedDecrement(&refs_);
        if (n == 0) delete this;
        return n;
    }

    STDMETHODIMP Next(ULONG count, IExplorerCommand** commands, ULONG* fetched) override {
        ULONG n = 0;
        while (n < count && pos_ < menu_->items.size()) {
            Command* command = new (std::nothrow) Command(menu_, static_cast<int>(pos_));
            if (!command) break;
            commands[n++] = command;
            pos_++;
        }
        if (fetched) *fetched = n;
        return n == count ? S_OK : S_FALSE;
    }
    STDMETHODIMP Skip(ULONG count) override {
        ULONG size = static_cast<ULONG>(menu_->items.size());
        bool enough = count <= size - pos_;
        pos_ = enough ? pos_ + count : size;
        return enough ? S_OK : S_FALSE;
    }
    STDMETHODIMP Reset() override {
        pos_ = 0;
        return S_OK;
    }
    STDMETHODIMP Clone(IEnumExplorerCommand** copy) override {
        *copy = new (std::nothrow) SubCommands(menu_, pos_);
        return *copy ? S_OK : E_OUTOFMEMORY;
    }

  private:
    ~SubCommands() { InterlockedDecrement(&g_locks); }

    LONG refs_ = 1;
    MenuPtr menu_;
    ULONG pos_;
};

STDMETHODIMP Command::EnumSubCommands(IEnumExplorerCommand** commands) {
    *commands = nullptr;
    if (!root() || !menu_) return E_NOTIMPL;
    *commands = new (std::nothrow) SubCommands(menu_);
    return *commands ? S_OK : E_OUTOFMEMORY;
}

// --- Serveur COM -------------------------------------------------------------------------

class Factory final : public IClassFactory {
  public:
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == IID_IUnknown || riid == IID_IClassFactory) {
            *ppv = static_cast<IClassFactory*>(this);
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }  // objet statique
    STDMETHODIMP_(ULONG) Release() override { return 1; }

    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        Command* command = new (std::nothrow) Command(load_menu(), -1);
        if (!command) return E_OUTOFMEMORY;
        HRESULT hr = command->QueryInterface(riid, ppv);
        command->Release();
        return hr;
    }
    STDMETHODIMP LockServer(BOOL lock) override {
        if (lock)
            InterlockedIncrement(&g_locks);
        else
            InterlockedDecrement(&g_locks);
        return S_OK;
    }
};

static Factory g_factory;

extern "C" HRESULT STDAPICALLTYPE DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (clsid != CLSID_QuickConvertMenu) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}

extern "C" HRESULT STDAPICALLTYPE DllCanUnloadNow() {
    return g_locks == 0 ? S_OK : S_FALSE;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
