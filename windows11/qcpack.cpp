// qcpack.exe : crée et signe le paquet MSIX du menu Windows 11, sans le Windows SDK.
//
//     qcpack.exe pack <dossier> <sortie.msix>     dossier = AppxManifest.xml + logos
//     qcpack.exe sign <paquet.msix> <empreinte>   certificat de Cert:\CurrentUser\My
//
// MakeAppx.exe et SignTool.exe (Windows SDK) ne font qu'appeler deux API livrées avec
// Windows : AppxPackaging.dll pour l'empaquetage, mssign32.dll (SignerSignEx2) pour la
// signature. On les appelle directement. Ces API n'ont pas d'en-tête pour MinGW : les
// déclarations ci-dessous suivent appxpackaging.h et la documentation de SignerSignEx2.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <shlwapi.h>
#include <urlmon.h>
#include <wincrypt.h>
#include <stdio.h>
#include <wchar.h>

// --- Empaquetage -------------------------------------------------------------------------

struct IAppxPackageWriter : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE AddPayloadFile(LPCWSTR fileName, LPCWSTR contentType,
                                                     int compression, IStream* input) = 0;
    virtual HRESULT STDMETHODCALLTYPE Close(IStream* manifest) = 0;
};

struct APPX_PACKAGE_SETTINGS {
    BOOL forceZip32;
    IUri* hashMethod;
};

struct IAppxFactory : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE CreatePackageWriter(IStream* output, APPX_PACKAGE_SETTINGS* settings,
                                                          IAppxPackageWriter** writer) = 0;
    // CreatePackageReader, CreateManifestReader... : inutiles ici.
};

static const CLSID CLSID_AppxFactory = {0x5842a140, 0xff9f, 0x4166, {0x8f, 0x5c, 0x62, 0xf5, 0xb7, 0xb0, 0xc7, 0x81}};
static const IID IID_IAppxFactory = {0xbeb94909, 0xe451, 0x438b, {0xb5, 0xa7, 0xd7, 0x9e, 0x76, 0x7b, 0x75, 0xd8}};
static const int APPX_COMPRESSION_OPTION_NORMAL = 1;

static const wchar_t* content_type(const wchar_t* name) {
    const wchar_t* ext = PathFindExtensionW(name);
    if (!_wcsicmp(ext, L".png")) return L"image/png";
    if (!_wcsicmp(ext, L".xml")) return L"application/xml";
    if (!_wcsicmp(ext, L".dll") || !_wcsicmp(ext, L".exe")) return L"application/x-msdownload";
    return L"application/octet-stream";
}

static HRESULT open_stream(const wchar_t* path, bool write, IStream** stream) {
    DWORD mode = write ? (STGM_CREATE | STGM_WRITE | STGM_SHARE_EXCLUSIVE) : (STGM_READ | STGM_SHARE_DENY_WRITE);
    return SHCreateStreamOnFileEx(path, mode, FILE_ATTRIBUTE_NORMAL, write, nullptr, stream);
}

// Ajoute récursivement le contenu de `root\rel` (rel = "" pour la racine).
static HRESULT add_dir(IAppxPackageWriter* writer, const wchar_t* root, const wchar_t* rel) {
    wchar_t pattern[MAX_PATH];
    swprintf(pattern, MAX_PATH, rel[0] ? L"%ls\\%ls\\*" : L"%ls\\*", root, rel);
    WIN32_FIND_DATAW fd;
    HANDLE find = FindFirstFileW(pattern, &fd);
    if (find == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
    HRESULT hr = S_OK;
    do {
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
        wchar_t name[MAX_PATH], full[MAX_PATH];
        swprintf(name, MAX_PATH, rel[0] ? L"%ls\\%ls" : L"%ls%ls", rel, fd.cFileName);
        swprintf(full, MAX_PATH, L"%ls\\%ls", root, name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            hr = add_dir(writer, root, name);
        } else if (_wcsicmp(name, L"AppxManifest.xml") != 0) {
            IStream* input = nullptr;
            hr = open_stream(full, false, &input);
            if (SUCCEEDED(hr)) {
                hr = writer->AddPayloadFile(name, content_type(name), APPX_COMPRESSION_OPTION_NORMAL, input);
                input->Release();
            }
            if (FAILED(hr)) fwprintf(stderr, L"qcpack: cannot add %ls (0x%08lx)\n", name, hr);
        }
    } while (SUCCEEDED(hr) && FindNextFileW(find, &fd));
    FindClose(find);
    return hr;
}

static HRESULT pack(const wchar_t* dir, const wchar_t* out) {
    IAppxFactory* factory = nullptr;
    IUri* sha256 = nullptr;
    IStream* output = nullptr;
    IStream* manifest = nullptr;
    IAppxPackageWriter* writer = nullptr;
    wchar_t manifest_path[MAX_PATH];
    swprintf(manifest_path, MAX_PATH, L"%ls\\AppxManifest.xml", dir);

    HRESULT hr = CoCreateInstance(CLSID_AppxFactory, nullptr, CLSCTX_INPROC_SERVER, IID_IAppxFactory,
                                  reinterpret_cast<void**>(&factory));
    // Empreintes SHA-256 dans AppxBlockMap.xml : la signature devra utiliser le même algorithme.
    if (SUCCEEDED(hr)) hr = CreateUri(L"http://www.w3.org/2001/04/xmlenc#sha256", Uri_CREATE_CANONICALIZE, 0, &sha256);
    if (SUCCEEDED(hr)) hr = open_stream(manifest_path, false, &manifest);
    if (SUCCEEDED(hr)) hr = open_stream(out, true, &output);
    if (SUCCEEDED(hr)) {
        APPX_PACKAGE_SETTINGS settings = {FALSE, sha256};
        hr = factory->CreatePackageWriter(output, &settings, &writer);
    }
    if (SUCCEEDED(hr)) hr = add_dir(writer, dir, L"");
    if (SUCCEEDED(hr)) hr = writer->Close(manifest);  // valide le manifeste, écrit AppxBlockMap.xml

    if (writer) writer->Release();
    if (output) output->Release();
    if (manifest) manifest->Release();
    if (sha256) sha256->Release();
    if (factory) factory->Release();
    if (FAILED(hr)) DeleteFileW(out);
    return hr;
}

// --- Signature ---------------------------------------------------------------------------

struct SIGNER_FILE_INFO {
    DWORD cbSize;
    LPCWSTR pwszFileName;
    HANDLE hFile;
};

struct SIGNER_SUBJECT_INFO {
    DWORD cbSize;
    DWORD* pdwIndex;
    DWORD dwSubjectChoice;
    SIGNER_FILE_INFO* pSignerFileInfo;  // union dont on n'utilise que ce membre
};

struct SIGNER_CERT_STORE_INFO {
    DWORD cbSize;
    PCCERT_CONTEXT pSigningCert;
    DWORD dwCertPolicy;
    HCERTSTORE hCertStore;
};

struct SIGNER_CERT {
    DWORD cbSize;
    DWORD dwCertChoice;
    SIGNER_CERT_STORE_INFO* pCertStoreInfo;  // union
    HWND hwnd;
};

struct SIGNER_SIGNATURE_INFO {
    DWORD cbSize;
    ALG_ID algidHash;
    DWORD dwAttrChoice;
    void* pAttrAuthcode;  // union
    PCRYPT_ATTRIBUTES psAuthenticated;
    PCRYPT_ATTRIBUTES psUnauthenticated;
};

struct SIGNER_SIGN_EX2_PARAMS {
    DWORD dwFlags;
    SIGNER_SUBJECT_INFO* pSubjectInfo;
    SIGNER_CERT* pSigningCert;
    SIGNER_SIGNATURE_INFO* pSignatureInfo;
    void* pProviderInfo;
    DWORD dwTimestampFlags;
    PCSTR pszAlgorithmOid;
    PCWSTR pwszTimestampURL;
    PCRYPT_ATTRIBUTES pCryptAttrs;
    void* pSipData;
    void** pSignerContext;
    void* pCryptoPolicy;
    void* pReserved;
};

// Données propres aux paquets MSIX : sans elles, SignerSignEx2 échoue avec 0x80080209
// (c'est le cas du vieux signtool.exe de ClickOnce).
struct APPX_SIP_CLIENT_DATA {
    SIGNER_SIGN_EX2_PARAMS* pSignerParams;
    IUnknown* pAppxSipState;
};

typedef HRESULT(WINAPI* SignerSignEx2Fn)(DWORD, SIGNER_SUBJECT_INFO*, SIGNER_CERT*, SIGNER_SIGNATURE_INFO*,
                                          void*, DWORD, PCSTR, PCWSTR, PCRYPT_ATTRIBUTES, void*, void**,
                                          void*, void*);

static const DWORD SIGNER_SUBJECT_FILE = 1;
static const DWORD SIGNER_CERT_STORE = 2;
static const DWORD SIGNER_CERT_POLICY_CHAIN_NO_ROOT = 8;
static const DWORD SIGNER_NO_ATTR = 0;

static PCCERT_CONTEXT find_cert(HCERTSTORE store, const wchar_t* thumbprint) {
    BYTE hash[20];
    if (wcslen(thumbprint) != 40) return nullptr;
    for (int i = 0; i < 20; i++) {
        unsigned value;
        if (swscanf(thumbprint + 2 * i, L"%2x", &value) != 1) return nullptr;
        hash[i] = static_cast<BYTE>(value);
    }
    CRYPT_HASH_BLOB blob = {sizeof(hash), hash};
    return CertFindCertificateInStore(store, X509_ASN_ENCODING | PKCS_7_ASN_ENCODING, 0, CERT_FIND_SHA1_HASH,
                                      &blob, nullptr);
}

static HRESULT sign(const wchar_t* package, const wchar_t* thumbprint) {
    HCERTSTORE store = CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0,
                                     CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG, L"My");
    if (!store) return HRESULT_FROM_WIN32(GetLastError());
    PCCERT_CONTEXT cert = find_cert(store, thumbprint);
    if (!cert) {
        CertCloseStore(store, 0);
        fwprintf(stderr, L"qcpack: certificate %ls not found in CurrentUser\\My\n", thumbprint);
        return CRYPT_E_NOT_FOUND;
    }

    DWORD index = 0;
    SIGNER_FILE_INFO file = {sizeof(file), package, nullptr};
    SIGNER_SUBJECT_INFO subject = {sizeof(subject), &index, SIGNER_SUBJECT_FILE, &file};
    SIGNER_CERT_STORE_INFO store_info = {sizeof(store_info), cert, SIGNER_CERT_POLICY_CHAIN_NO_ROOT, nullptr};
    SIGNER_CERT signer_cert = {sizeof(signer_cert), SIGNER_CERT_STORE, &store_info, nullptr};
    SIGNER_SIGNATURE_INFO signature = {sizeof(signature), CALG_SHA_256, SIGNER_NO_ATTR, nullptr, nullptr, nullptr};
    SIGNER_SIGN_EX2_PARAMS params = {};
    params.pSubjectInfo = &subject;
    params.pSigningCert = &signer_cert;
    params.pSignatureInfo = &signature;
    APPX_SIP_CLIENT_DATA sip = {&params, nullptr};
    params.pSipData = &sip;

    HRESULT hr = E_FAIL;
    HMODULE mssign = LoadLibraryExW(L"mssign32.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    SignerSignEx2Fn signer_sign = mssign ? reinterpret_cast<SignerSignEx2Fn>(
                                               reinterpret_cast<void*>(GetProcAddress(mssign, "SignerSignEx2")))
                                         : nullptr;
    if (signer_sign) {
        hr = signer_sign(params.dwFlags, params.pSubjectInfo, params.pSigningCert, params.pSignatureInfo,
                         params.pProviderInfo, params.dwTimestampFlags, params.pszAlgorithmOid,
                         params.pwszTimestampURL, params.pCryptAttrs, params.pSipData, params.pSignerContext,
                         params.pCryptoPolicy, params.pReserved);
    } else {
        hr = HRESULT_FROM_WIN32(GetLastError());
    }
    if (sip.pAppxSipState) sip.pAppxSipState->Release();
    if (mssign) FreeLibrary(mssign);
    CertFreeCertificateContext(cert);
    CertCloseStore(store, 0);
    return hr;
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 4 || (wcscmp(argv[1], L"pack") != 0 && wcscmp(argv[1], L"sign") != 0)) {
        fwprintf(stderr, L"usage: qcpack pack <folder> <out.msix>\n"
                         L"       qcpack sign <package.msix> <sha1-thumbprint>\n");
        return 2;
    }
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    bool packing = wcscmp(argv[1], L"pack") == 0;
    HRESULT hr = packing ? pack(argv[2], argv[3]) : sign(argv[2], argv[3]);
    CoUninitialize();
    if (FAILED(hr)) {
        fwprintf(stderr, L"qcpack: %ls failed (0x%08lx)\n", packing ? L"packaging" : L"signing", hr);
        return 1;
    }
    return 0;
}
