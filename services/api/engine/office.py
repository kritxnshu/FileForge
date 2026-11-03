"""LibreOffice (headless) runner.

Hazards handled (SECURITY.md):
  * macros: execution disabled and macro security set to "very high" in a fresh per-job profile
  * linked files / external data / WEBSERVICE: link updates set to "never", formulas never
    recalculated on load (cached results are used), and the whole process has no network
  * a separate `-env:UserInstallation` per job also makes parallel conversions safe
LibreOffice reports no progress, so callers show stage labels only.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .context import ConversionError, Ctx
from .registry import soffice_path

_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="UseDocumentSystemFileLocking" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Setup/Office"><prop oor:name="ooSetupInstCompleted" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Save/Document"><prop oor:name="CreateBackup" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Recovery/AutoSave"><prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"""

# LibreOffice output filter per target format
FILTERS = {
    "pdf": "pdf",
    "docx": 'docx:"MS Word 2007 XML"',
    "doc": 'doc:"MS Word 97"',
    "odt": "odt:writer8",
    "rtf": 'rtf:"Rich Text Format"',
    "txt": 'txt:Text (encoded):UTF8',
    "xlsx": 'xlsx:"Calc MS Excel 2007 XML"',
    "xls": 'xls:"MS Excel 97"',
    "ods": "ods:calc8",
    "pptx": 'pptx:"Impress MS PowerPoint 2007 XML"',
    "ppt": 'ppt:"MS PowerPoint 97"',
    "odp": "odp:impress8",
    "html": "html",
}


def _profile(ctx: Ctx) -> Path:
    prof = ctx.work_dir / "lo-profile"
    user = prof / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(_XCU)
    return prof


def convert(ctx: Ctx, src: Path, target: str, *, filter_override: str | None = None, infilter: str | None = None,
            out_dir: Path | None = None) -> Path:
    exe = soffice_path()
    if not exe:
        raise ConversionError("engine_missing", "LibreOffice isn't installed on this server.")
    prof = _profile(ctx)
    out_dir = out_dir or (ctx.work_dir / "lo-out")
    out_dir.mkdir(parents=True, exist_ok=True)
    flt = filter_override or FILTERS[target]
    cmd = [exe, "--headless", "--invisible", "--norestore", "--nologo", "--nodefault", "--nolockcheck", "--nofirststartwizard",
           f"-env:UserInstallation={prof.resolve().as_uri()}"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", flt.replace('"', ""), "--outdir", str(out_dir), str(src)]
    ctx.stage("Converting with LibreOffice")
    res = ctx.run(cmd, check=False, env={"SAL_USE_VCLPLUGIN": "svp", "HOME": str(ctx.job_dir / "home")})
    ext = flt.split(":")[0]
    produced = out_dir / f"{src.stem}.{ext}"
    if res.returncode != 0 or not produced.exists() or produced.stat().st_size == 0:
        text = (res.stderr_tail + res.stdout.decode("utf-8", "replace")).lower()
        if "password" in text:
            raise ConversionError("password_required", "This document is password-protected. Remove the password and try again.")
        raise ConversionError("engine_error", "LibreOffice couldn't convert this file. It may be damaged or use unsupported features.")
    return produced


def convert_to_output(ctx: Ctx, src: Path, target: str, **kw) -> Path:
    produced = convert(ctx, src, target, **kw)
    out = ctx.default_out(target)
    shutil.move(str(produced), out)
    return out
