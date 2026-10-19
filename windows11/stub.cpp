// RightClick-Converter.exe : l'exécutable qu'exige le manifeste du paquet (élément Application).
// Le paquet ne sert qu'au menu clic droit ; lancé directement, ce programme le rappelle.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    MessageBoxW(nullptr,
                L"RightClick-Converter s'utilise depuis le clic droit de l'Explorateur :\n"
                L"sélectionner des images, puis « Convertir en ».",
                L"RightClick-Converter", MB_OK | MB_ICONINFORMATION);
    return 0;
}
