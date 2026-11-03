"""Entry point of a sandboxed job process: `python -I -m engine.child <job_dir>`.

Reads `<job_dir>/spec.json`, runs one operation, writes `result.json` (or
`error.json`) and reports progress as JSON lines on the original stdout.
Everything a library prints goes to stderr so it can't corrupt the progress
stream.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def main(job_dir_arg: str) -> int:
    progress_fd = os.dup(1)
    os.dup2(2, 1)  # library prints -> stderr
    sys.stdout = sys.stderr
    out = os.fdopen(progress_fd, "w", buffering=1)

    def emit(ev: dict) -> None:
        out.write(json.dumps(ev) + "\n")

    job_dir = Path(job_dir_arg).resolve()
    spec = json.loads((job_dir / "spec.json").read_text())

    from .context import ConversionError, Ctx, InputFile, write_json
    from .registry import get
    from .safety import apply_global_limits

    apply_global_limits(spec.get("limits", {}))
    try:
        op = get(spec["operation"])
        if op is None or op.run is None:
            raise ConversionError("unsupported", "This operation isn't available.")
        options = op.options.model_validate(spec.get("options") or {})
        ctx = Ctx(
            inputs=[InputFile(Path(i["path"]), i["format"], i["size"], n, i.get("stem", f"file{n + 1}"))
                    for n, i in enumerate(spec["inputs"])],
            target=spec["target"],
            options=options,
            out_dir=job_dir / "out",
            work_dir=job_dir / "work",
            job_dir=job_dir,
            timeout_s=float(spec.get("timeout_s", 60)),
            emit=emit,
        )
        ctx.out_dir.mkdir(exist_ok=True)
        ctx.work_dir.mkdir(exist_ok=True)
        emit({"t": "progress", "stage": "Converting"})
        op.run(ctx)
        if not ctx.outputs:
            raise ConversionError("engine_error", "The conversion produced no output.")
        emit({"t": "progress", "stage": "Finalizing"})
        write_json(job_dir / "result.json", {
            "outputs": [{"path": str(o.path.relative_to(job_dir)), "format": o.format, "label": o.label,
                         "size": o.path.stat().st_size} for o in ctx.outputs],
            "notices": ctx.notices,
            "warnings": ctx.warnings,
            "info": ctx.info,
        })
        return 0
    except ConversionError as e:
        write_json(job_dir / "error.json", {"code": e.code, "message": e.message})
        return 2
    except MemoryError:
        write_json(job_dir / "error.json", {"code": "too_large", "message": "This file needs more memory than we allow for one conversion."})
        return 3
    except Exception as e:  # unexpected: classify, never leak internals to the user
        from .safety import classify_exception

        code, message = classify_exception(e)
        traceback.print_exc(file=sys.stderr)
        write_json(job_dir / "error.json", {"code": code, "message": message})
        return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
