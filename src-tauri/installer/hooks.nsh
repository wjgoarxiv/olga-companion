; Installer hooks for the NSIS bundle (tauri.conf.json bundle.windows.nsis.installerHooks).

; An update copies new files over the old install and never removes the old ones, so a file a
; newer version dropped would stay behind. Clear the app's own resource folders first; the
; install that follows writes them again in full. The app is closed first (the same check the
; installer makes next), so an install cancelled at that prompt leaves the old app whole.
!macro NSIS_HOOK_PREINSTALL
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  RMDir /r "$INSTDIR\resources\olga-toolkit"
  RMDir /r "$INSTDIR\resources\fluids"
  RMDir /r "$INSTDIR\resources\tutorial"
  RMDir /r "$INSTDIR\resources\examples"
!macroend
