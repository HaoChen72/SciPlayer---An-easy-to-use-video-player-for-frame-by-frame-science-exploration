; SciPlayer installer - Windows 11, 64-bit only. English, 简体中文, 繁體中文 (asked first; the choice
; also becomes SciPlayer's own language). This file is UTF-8 with a byte-order mark.
; Installs for all users (Program Files, needs administrator rights) or just for the current user
; (no administrator rights needed), adds a Start-menu entry, registers SciPlayer for video files,
; TIFF stacks and MAT-files ("Open with", Default apps), and an uninstaller.
;   makensis -DVERSION=1.0.0 -DSTAGE=<installation folder> -DASSETS=<icons> -DOUTFILE=<setup.exe> sciplayer.nsi

Target amd64-unicode                    ; a 64-bit installer: it starts only on 64-bit Windows
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ManifestDPIAware true
ManifestSupportedOS Win10                    ; (Windows 10's ID is also Windows 11's)

!define APP        "SciPlayer"
!define PROGID     "SciPlayer.Recording"
!define REGKEY     "Software\SciPlayer"
!define UNINSTKEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\SciPlayer"
!define PUBLISHER  "SciPlayer"

Name "${APP} ${VERSION}"
OutFile "${OUTFILE}"
BrandingText "${APP} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "FileDescription" "${APP} setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "LegalCopyright" "${PUBLISHER}"

; ---- all users or just me ---------------------------------------------------------------------
!define MULTIUSER_EXECUTIONLEVEL Highest
!define MULTIUSER_MUI
!define MULTIUSER_INSTALLMODE_COMMANDLINE
!define MULTIUSER_USE_PROGRAMFILES64
!define MULTIUSER_INSTALLMODE_INSTDIR "${APP}"
!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${REGKEY}"
!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "InstallMode"
!define MULTIUSER_INSTALLMODE_INSTDIR_REGISTRY_KEY "${REGKEY}"
!define MULTIUSER_INSTALLMODE_INSTDIR_REGISTRY_VALUENAME "InstallLocation"
!include MultiUser.nsh
!include MUI2.nsh
!include LogicLib.nsh
!include x64.nsh
!include WinVer.nsh
!include FileFunc.nsh

; ---- pages ----------------------------------------------------------------------------------
!define MUI_ICON "${ASSETS}/sciplayer.ico"
!define MUI_UNICON "${ASSETS}/sciplayer.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "${ASSETS}/header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${ASSETS}/welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${ASSETS}/welcome.bmp"
!define MUI_ABORTWARNING
; the language asked when the installer starts (and remembered for the uninstaller)
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${REGKEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "InstallerLanguage"
!define MUI_LANGDLL_ALLLANGUAGES
!define MUI_LANGDLL_ALWAYSSHOW      ; asked every time (the last choice preselected), also when installing over a version
!define MUI_WELCOMEPAGE_TEXT "$(T_WELCOME)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${STAGE}\LICENSE.txt"   ; the terms: free for non-commercial use (PolyForm Noncommercial 1.0.0)
!insertmacro MULTIUSER_PAGE_INSTALLMODE
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\SciPlayer.exe"
!define MUI_FINISHPAGE_RUN_TEXT "$(T_RUN)"
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(T_DEFAULTS)"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION open_default_apps
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "TradChinese"
!insertmacro MUI_RESERVEFILE_LANGDLL

LangString T_WELCOME ${LANG_ENGLISH} "SciPlayer is a video player for scientific recordings: scrub and play any video, TIFF stack or MAT-file, see the relative change (dF/F) against a baseline you choose, and follow the mean intensity of the whole frame and of your own regions over time.$\r$\n$\r$\nEverything it needs is included; nothing else has to be installed.$\r$\n$\r$\nClick Next to continue."
LangString T_WELCOME ${LANG_SIMPCHINESE} "SciPlayer 是为科学记录设计的视频播放器：可流畅拖动、逐帧查看和播放任何视频、TIFF 序列或 MAT 文件，显示相对于所选基线的相对变化 (dF/F)，并跟踪整个画面及自定义区域的平均强度随时间的变化。$\r$\n$\r$\n所需的一切均已包含，无需另外安装任何软件。$\r$\n$\r$\n单击“下一步”继续。"
LangString T_WELCOME ${LANG_TRADCHINESE} "SciPlayer 是為科學記錄設計的影片播放器：可流暢拖曳、逐格檢視與播放任何影片、TIFF 序列或 MAT 檔，顯示相對於所選基線的相對變化 (dF/F)，並追蹤整個畫面及自訂區域的平均強度隨時間的變化。$\r$\n$\r$\n所需的一切均已包含，無需另外安裝任何軟體。$\r$\n$\r$\n按「下一步」繼續。"
LangString T_RUN ${LANG_ENGLISH} "Start SciPlayer"
LangString T_RUN ${LANG_SIMPCHINESE} "启动 SciPlayer"
LangString T_RUN ${LANG_TRADCHINESE} "啟動 SciPlayer"
LangString T_DEFAULTS ${LANG_ENGLISH} "Choose SciPlayer as the default app for video files (opens Windows Settings)"
LangString T_DEFAULTS ${LANG_SIMPCHINESE} "将 SciPlayer 设为视频文件的默认应用（打开 Windows 设置）"
LangString T_DEFAULTS ${LANG_TRADCHINESE} "將 SciPlayer 設為影片檔案的預設應用程式（開啟 Windows 設定）"
LangString T_SEC_MAIN ${LANG_ENGLISH} "SciPlayer (required)"
LangString T_SEC_MAIN ${LANG_SIMPCHINESE} "SciPlayer（必需）"
LangString T_SEC_MAIN ${LANG_TRADCHINESE} "SciPlayer（必要）"
LangString T_SEC_ASSOC ${LANG_ENGLISH} "Open files that have no program yet with SciPlayer"
LangString T_SEC_ASSOC ${LANG_SIMPCHINESE} "尚无打开程序的文件用 SciPlayer 打开"
LangString T_SEC_ASSOC ${LANG_TRADCHINESE} "尚無開啟程式的檔案以 SciPlayer 開啟"
LangString T_SEC_DESKTOP ${LANG_ENGLISH} "Desktop shortcut"
LangString T_SEC_DESKTOP ${LANG_SIMPCHINESE} "桌面快捷方式"
LangString T_SEC_DESKTOP ${LANG_TRADCHINESE} "桌面捷徑"
LangString T_DESC_MAIN ${LANG_ENGLISH} "SciPlayer with everything it needs (Python, Qt, FFmpeg). Registers it for video files, TIFF stacks and MAT-files under Open with."
LangString T_DESC_MAIN ${LANG_SIMPCHINESE} "SciPlayer 及其所需的一切（Python、Qt、FFmpeg）。在“打开方式”中为视频文件、TIFF 序列和 MAT 文件注册 SciPlayer。"
LangString T_DESC_MAIN ${LANG_TRADCHINESE} "SciPlayer 及其所需的一切（Python、Qt、FFmpeg）。在「開啟檔案」中為影片檔、TIFF 序列與 MAT 檔註冊 SciPlayer。"
LangString T_DESC_ASSOC ${LANG_ENGLISH} "Video and TIFF extensions that no program opens yet open with SciPlayer on a double-click. Defaults of other programs are left alone: change them in Settings > Default apps."
LangString T_DESC_ASSOC ${LANG_SIMPCHINESE} "尚无程序打开的视频和 TIFF 扩展名，双击时用 SciPlayer 打开。其他程序的默认设置保持不变，可在“设置 > 默认应用”中更改。"
LangString T_DESC_ASSOC ${LANG_TRADCHINESE} "尚無程式開啟的影片與 TIFF 副檔名，按兩下時以 SciPlayer 開啟。其他程式的預設設定維持不變，可在「設定 > 預設應用程式」中變更。"
LangString T_DESC_DESKTOP ${LANG_ENGLISH} "A SciPlayer icon on the desktop."
LangString T_DESC_DESKTOP ${LANG_SIMPCHINESE} "在桌面上放置 SciPlayer 图标。"
LangString T_DESC_DESKTOP ${LANG_TRADCHINESE} "在桌面上放置 SciPlayer 圖示。"
LangString T_NEED64 ${LANG_ENGLISH} "SciPlayer needs 64-bit Windows 11."
LangString T_NEED64 ${LANG_SIMPCHINESE} "SciPlayer 需要 64 位 Windows 11。"
LangString T_NEED64 ${LANG_TRADCHINESE} "SciPlayer 需要 64 位元 Windows 11。"
LangString T_NEED11 ${LANG_ENGLISH} "SciPlayer needs Windows 11 (64-bit)."
LangString T_NEED11 ${LANG_SIMPCHINESE} "SciPlayer 需要 Windows 11（64 位）。"
LangString T_NEED11 ${LANG_TRADCHINESE} "SciPlayer 需要 Windows 11（64 位元）。"
LangString T_TYPE ${LANG_ENGLISH} "SciPlayer recording"
LangString T_TYPE ${LANG_SIMPCHINESE} "SciPlayer 记录"
LangString T_TYPE ${LANG_TRADCHINESE} "SciPlayer 記錄"
LangString T_APPDESC ${LANG_ENGLISH} "Video player for scientific recordings: dF/F, ROI traces"
LangString T_APPDESC ${LANG_SIMPCHINESE} "科学记录视频播放器：dF/F、ROI 曲线"
LangString T_APPDESC ${LANG_TRADCHINESE} "科學記錄影片播放器：dF/F、ROI 曲線"
LangString T_APPLANG ${LANG_ENGLISH} "en"
LangString T_APPLANG ${LANG_SIMPCHINESE} "zh_CN"
LangString T_APPLANG ${LANG_TRADCHINESE} "zh_TW"

; ---- the formats ------------------------------------------------------------------------------
; for each: "Open with" SciPlayer always; SciPlayer as the default only where the extension has no
; default program yet (Windows 11 lets the user choose defaults: see the finish page)
!macro for_each_format MACRO
  !insertmacro ${MACRO} ".avi"   "video"
  !insertmacro ${MACRO} ".mp4"   "video"
  !insertmacro ${MACRO} ".m4v"   "video"
  !insertmacro ${MACRO} ".mov"   "video"
  !insertmacro ${MACRO} ".mkv"   "video"
  !insertmacro ${MACRO} ".wmv"   "video"
  !insertmacro ${MACRO} ".mpg"   "video"
  !insertmacro ${MACRO} ".mpeg"  "video"
  !insertmacro ${MACRO} ".mj2"   "video"
  !insertmacro ${MACRO} ".mjpg"  "video"
  !insertmacro ${MACRO} ".mjpeg" "video"
  !insertmacro ${MACRO} ".webm"  "video"
  !insertmacro ${MACRO} ".flv"   "video"
  !insertmacro ${MACRO} ".ogv"   "video"
  !insertmacro ${MACRO} ".3gp"   "video"
  !insertmacro ${MACRO} ".mts"   "video"
  !insertmacro ${MACRO} ".m2ts"  "video"
  !insertmacro ${MACRO} ".vob"   "video"
  !insertmacro ${MACRO} ".tif"   "stack"
  !insertmacro ${MACRO} ".tiff"  "stack"
  !insertmacro ${MACRO} ".mat"   "stack"
!macroend

!macro register_format EXT KIND
  WriteRegStr SHCTX "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}" ""
  WriteRegStr SHCTX "Software\Classes\Applications\SciPlayer.exe\SupportedTypes" "${EXT}" ""
  WriteRegStr SHCTX "${REGKEY}\Capabilities\FileAssociations" "${EXT}" "${PROGID}"
!macroend

; SciPlayer as the default program only where the extension has none
; (never for .mat: that belongs to MATLAB wherever MATLAB is installed)
!macro default_if_none EXT KIND
  !if "${EXT}" != ".mat"
    ReadRegStr $0 HKCR "${EXT}" ""
    ${If} $0 == ""
      WriteRegStr SHCTX "Software\Classes\${EXT}" "" "${PROGID}"
      WriteRegStr SHCTX "${REGKEY}\DefaultsSet" "${EXT}" "1"
    ${EndIf}
  !endif
!macroend

!macro unregister_format EXT KIND
  DeleteRegValue SHCTX "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}"
  DeleteRegKey /ifempty SHCTX "Software\Classes\${EXT}\OpenWithProgids"
  ReadRegStr $0 SHCTX "${REGKEY}\DefaultsSet" "${EXT}"
  ${If} $0 == "1"
    ReadRegStr $1 SHCTX "Software\Classes\${EXT}" ""
    ${If} $1 == "${PROGID}"
      DeleteRegValue SHCTX "Software\Classes\${EXT}" ""
    ${EndIf}
  ${EndIf}
  DeleteRegKey /ifempty SHCTX "Software\Classes\${EXT}"
!macroend

; ---- install ----------------------------------------------------------------------------------
Section "$(T_SEC_MAIN)" sec_main
  SectionIn RO
  ; a running SciPlayer would keep its files locked
  nsExec::Exec 'taskkill /im SciPlayer.exe /f'
  Pop $0
  ; a previous version: its files go first (the runtime may have changed)
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  SetOutPath "$INSTDIR"
  File /r "${STAGE}/*.*"
  WriteUninstaller "$INSTDIR\Uninstall SciPlayer.exe"

  ; the program and its document type
  WriteRegStr SHCTX "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr SHCTX "${REGKEY}" "InstallMode" "$MultiUser.InstallMode"
  WriteRegStr SHCTX "${REGKEY}" "Version" "${VERSION}"
  WriteRegStr SHCTX "Software\Classes\${PROGID}" "" "$(T_TYPE)"
  WriteRegStr SHCTX "Software\Classes\${PROGID}" "FriendlyTypeName" "$(T_TYPE)"
  WriteRegStr SHCTX "Software\Classes\${PROGID}\DefaultIcon" "" '"$INSTDIR\SciPlayer.exe",0'
  WriteRegStr SHCTX "Software\Classes\${PROGID}\shell" "" "open"
  WriteRegStr SHCTX "Software\Classes\${PROGID}\shell\open" "FriendlyAppName" "SciPlayer"
  WriteRegStr SHCTX "Software\Classes\${PROGID}\shell\open\command" "" '"$INSTDIR\SciPlayer.exe" "%1"'
  WriteRegStr SHCTX "Software\Classes\Applications\SciPlayer.exe" "FriendlyAppName" "SciPlayer"
  WriteRegStr SHCTX "Software\Classes\Applications\SciPlayer.exe\DefaultIcon" "" '"$INSTDIR\SciPlayer.exe",0'
  WriteRegStr SHCTX "Software\Classes\Applications\SciPlayer.exe\shell\open\command" "" '"$INSTDIR\SciPlayer.exe" "%1"'
  WriteRegStr SHCTX "Software\Microsoft\Windows\CurrentVersion\App Paths\SciPlayer.exe" "" "$INSTDIR\SciPlayer.exe"
  WriteRegStr SHCTX "Software\Microsoft\Windows\CurrentVersion\App Paths\SciPlayer.exe" "Path" "$INSTDIR"
  ; Default apps (Settings) knows SciPlayer through its capabilities
  WriteRegStr SHCTX "${REGKEY}\Capabilities" "ApplicationName" "SciPlayer"
  WriteRegStr SHCTX "${REGKEY}\Capabilities" "ApplicationDescription" "$(T_APPDESC)"
  WriteRegStr SHCTX "${REGKEY}\Capabilities" "ApplicationIcon" '"$INSTDIR\SciPlayer.exe",0'
  WriteRegStr SHCTX "Software\RegisteredApplications" "SciPlayer" "${REGKEY}\Capabilities"
  !insertmacro for_each_format register_format

  ; Start menu
  CreateShortcut "$SMPROGRAMS\SciPlayer.lnk" "$INSTDIR\SciPlayer.exe" "" "$INSTDIR\SciPlayer.exe" 0 SW_SHOWNORMAL "" "$(T_APPDESC)"

  ; Apps & features
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "SciPlayer"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" '"$INSTDIR\SciPlayer.exe",0'
  WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall SciPlayer.exe" /$MultiUser.InstallMode'
  WriteRegStr SHCTX "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall SciPlayer.exe" /$MultiUser.InstallMode /S'
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD SHCTX "${UNINSTKEY}" "EstimatedSize" "$0"

  ; SciPlayer starts in the language chosen here (it can be changed in its window)
  WriteRegStr HKCU "Software\SciPlayer\SciPlayer" "language" "$(T_APPLANG)"

  ; Explorer: new associations and icons now
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Section "$(T_SEC_ASSOC)" sec_assoc
  !insertmacro for_each_format default_if_none
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Section /o "$(T_SEC_DESKTOP)" sec_desktop
  CreateShortcut "$DESKTOP\SciPlayer.lnk" "$INSTDIR\SciPlayer.exe" "" "$INSTDIR\SciPlayer.exe" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${sec_main} "$(T_DESC_MAIN)"
  !insertmacro MUI_DESCRIPTION_TEXT ${sec_assoc} "$(T_DESC_ASSOC)"
  !insertmacro MUI_DESCRIPTION_TEXT ${sec_desktop} "$(T_DESC_DESKTOP)"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  SetRegView 64
  !insertmacro MUI_LANGDLL_DISPLAY
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "$(T_NEED64)" /SD IDOK
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin11}
    MessageBox MB_ICONSTOP "$(T_NEED11)" /SD IDOK
    Abort
  ${EndIf}
  !insertmacro MULTIUSER_INIT
FunctionEnd

Function open_default_apps
  ${If} $MultiUser.InstallMode == "AllUsers"
    ExecShell "open" "ms-settings:defaultapps?registeredAppMachine=SciPlayer"
  ${Else}
    ExecShell "open" "ms-settings:defaultapps?registeredAppUser=SciPlayer"
  ${EndIf}
FunctionEnd

; ---- uninstall ---------------------------------------------------------------------------------
Section "Uninstall"
  nsExec::Exec 'taskkill /im SciPlayer.exe /f'
  Pop $0
  !insertmacro for_each_format unregister_format
  DeleteRegKey SHCTX "Software\Classes\${PROGID}"
  DeleteRegKey SHCTX "Software\Classes\Applications\SciPlayer.exe"
  DeleteRegKey SHCTX "Software\Microsoft\Windows\CurrentVersion\App Paths\SciPlayer.exe"
  DeleteRegValue SHCTX "Software\RegisteredApplications" "SciPlayer"
  DeleteRegKey SHCTX "${REGKEY}"
  DeleteRegKey SHCTX "${UNINSTKEY}"
  Delete "$SMPROGRAMS\SciPlayer.lnk"
  Delete "$DESKTOP\SciPlayer.lnk"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\SciPlayer.exe"
  Delete "$INSTDIR\LICENSES.txt"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\Uninstall SciPlayer.exe"
  RMDir "$INSTDIR"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Function un.onInit
  SetRegView 64
  !insertmacro MUI_UNGETLANGUAGE
  !insertmacro MULTIUSER_UNINIT
FunctionEnd
