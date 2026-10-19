// test_menu.exe : charge RightClick-Converter.dll comme le fait l'Explorateur et affiche ce
// que verrait le menu pour une sélection donnée. Utilisé par tests/test_windows11.py.
//
//     test_menu.exe <dll> <libellé à cliquer | -> <fichier>... | @<liste UTF-8>
//
// Sortie (UTF-8, une ligne par élément) :
//     root|<titre>|<état>|<drapeaux>|<icône>
//     sub|<titre>|<état>                    état : 0 visible, 2 caché (EXPCMDSTATE)
//     invoke|<HRESULT>
//     unload|<HRESULT de DllCanUnloadNow>  0 = plus aucun objet vivant

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <stdio.h>
#include <string>
#include <vector>

static const CLSID CLSID_QuickConvertMenu = {0x8d81aa34, 0x5215, 0x40f5, {0x94, 0x70, 0xfb, 0xe3, 0x5a, 0x5f, 0xd6, 0x02}};

static void out(const std::wstring& line) {
    std::wstring text = line + L"\n";
    int n = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    std::string bytes(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), &bytes[0], n, nullptr, nullptr);
    fwrite(bytes.data(), 1, bytes.size(), stdout);
}

static std::wstring take(LPWSTR s) {
    std::wstring value = s ? s : L"";
    CoTaskMemFree(s);
    return value;
}

// Une sélection de centaines de fichiers ne tient pas dans la ligne de commande non plus.
static std::vector<std::wstring> read_list(const wchar_t* path) {
    std::vector<std::wstring> files;
    FILE* f = _wfopen(path, L"rb");
    if (!f) return files;
    std::string bytes;
    char buffer[4096];
    for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;) bytes.append(buffer, n);
    fclose(f);
    int n = MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
    std::wstring text(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), &text[0], n);
    size_t start = 0;
    while (start < text.size()) {
        size_t end = text.find(L'\n', start);
        if (end == std::wstring::npos) end = text.size();
        std::wstring line = text.substr(start, end - start);
        if (!line.empty() && line.back() == L'\r') line.pop_back();
        if (!line.empty()) files.push_back(line);
        start = end + 1;
    }
    return files;
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 4) {
        fwprintf(stderr, L"usage: test_menu <dll> <label|-> <file>...\n");
        return 2;
    }
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    HMODULE dll = LoadLibraryW(argv[1]);
    if (!dll) return 3;
    using GetClassObject = HRESULT(STDAPICALLTYPE*)(REFCLSID, REFIID, void**);
    using CanUnloadNow = HRESULT(STDAPICALLTYPE*)();
    auto get_class_object = reinterpret_cast<GetClassObject>(reinterpret_cast<void*>(GetProcAddress(dll, "DllGetClassObject")));
    auto can_unload = reinterpret_cast<CanUnloadNow>(reinterpret_cast<void*>(GetProcAddress(dll, "DllCanUnloadNow")));
    if (!get_class_object || !can_unload) return 4;

    std::vector<std::wstring> files(argv + 3, argv + argc);
    if (argc == 4 && argv[3][0] == L'@') files = read_list(argv[3] + 1);
    std::vector<PIDLIST_ABSOLUTE> pidls;
    for (const std::wstring& file : files) {
        PIDLIST_ABSOLUTE pidl = nullptr;
        if (FAILED(SHParseDisplayName(file.c_str(), nullptr, &pidl, 0, nullptr))) return 5;
        pidls.push_back(pidl);
    }
    IShellItemArray* items = nullptr;
    if (FAILED(SHCreateShellItemArrayFromIDLists(static_cast<UINT>(pidls.size()),
                                                 const_cast<PCIDLIST_ABSOLUTE*>(
                                                     reinterpret_cast<PIDLIST_ABSOLUTE*>(pidls.data())),
                                                 &items)))
        return 6;

    IClassFactory* factory = nullptr;
    IExplorerCommand* root = nullptr;
    if (FAILED(get_class_object(CLSID_QuickConvertMenu, IID_IClassFactory, reinterpret_cast<void**>(&factory))) ||
        FAILED(factory->CreateInstance(nullptr, __uuidof(IExplorerCommand), reinterpret_cast<void**>(&root))))
        return 7;
    factory->Release();

    EXPCMDSTATE state = 0;
    EXPCMDFLAGS flags = 0;
    LPWSTR title = nullptr, icon = nullptr;
    root->GetState(items, TRUE, &state);
    root->GetFlags(&flags);
    root->GetTitle(items, &title);
    root->GetIcon(items, &icon);
    out(L"root|" + take(title) + L"|" + std::to_wstring(state) + L"|" + std::to_wstring(flags) + L"|" + take(icon));

    IEnumExplorerCommand* subs = nullptr;
    if (SUCCEEDED(root->EnumSubCommands(&subs))) {
        IExplorerCommand* sub = nullptr;
        ULONG fetched = 0;
        while (subs->Next(1, &sub, &fetched) == S_OK && fetched == 1) {
            LPWSTR sub_title = nullptr;
            sub->GetTitle(items, &sub_title);
            sub->GetState(items, TRUE, &state);
            std::wstring name = take(sub_title);
            out(L"sub|" + name + L"|" + std::to_wstring(state));
            if (name == argv[2]) {
                HRESULT hr = sub->Invoke(items, nullptr);
                out(L"invoke|" + std::to_wstring(static_cast<long>(hr)));
            }
            sub->Release();
        }
        subs->Release();
    }
    root->Release();
    items->Release();
    for (PIDLIST_ABSOLUTE pidl : pidls) CoTaskMemFree(pidl);
    out(L"unload|" + std::to_wstring(static_cast<long>(can_unload())));
    CoUninitialize();
    return 0;
}
