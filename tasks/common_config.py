"""Common configuration for AgentHLE tasks.

Data-root injection
===================
Every task's on-VM paths hang off a single value: the *data root* (e.g.
``/media/user/data/ale-data`` on linux, ``E:\\ale-data`` on windows). That
value is not known until a VM has been provisioned, so the framework injects
it at run time via a context variable (:data:`_DATA_ROOT`) rather than having
each task hardcode it.

Task configs read the root through the :pyattr:`GeneralTaskConfig.data_root`
property; all path properties (``task_dir``, ``input_dir``, ``output_dir``,
``reference_dir``, ``software_dir``) derive from it. A task MUST NOT set the
root itself — there is no field to override. The framework calls
:func:`set_data_root` (once per run unit, inside that unit's own asyncio task)
before reading any path; because the binding lives in a ``ContextVar`` it is
isolated per asyncio task, so concurrent run units each see their own root
with zero cross-talk.

If a path is read before the root is injected, the property raises rather than
silently producing a wrong path.
"""

from __future__ import annotations

import contextvars
import json
import os
from dataclasses import dataclass
from pathlib import Path

_TASKS_ROOT = Path(__file__).resolve().parent


# Per-run-unit data root. Bound by the framework (set_data_root) after a VM is
# provisioned; read by GeneralTaskConfig.data_root. A ContextVar (not a module
# global) so concurrent run units, each driven in its own asyncio task, see
# independent values.
_DATA_ROOT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ale_data_root", default=None
)


def set_data_root(data_root: str) -> contextvars.Token:
    """Bind the data root for the current context (one run unit).

    Returns the ``Token`` from :meth:`ContextVar.set`; pass it to
    :func:`reset_data_root` to restore the previous binding when the unit ends.
    The framework owns these calls — task code never invokes them.
    """
    return _DATA_ROOT.set(data_root)


def reset_data_root(token: contextvars.Token) -> None:
    """Restore the data-root binding replaced by :func:`set_data_root`."""
    _DATA_ROOT.reset(token)


def get_data_root() -> str | None:
    """Current data root, or ``None`` if the framework hasn't injected one."""
    return _DATA_ROOT.get()


@dataclass
class GeneralTaskConfig:
    """Base configuration for Windows tasks (default OS).

    Primary fields follow the canonical domain/task/variant hierarchy:
      - DOMAIN_NAME: top-level task family. One of:
            engineering, physical_sciences, life_sciences, health_medicine,
            psychology_neuro, business_finance, legal, visual_media,
            computing_math, transport_safety, education_info, agriculture_env,
            social_sciences, other
      - TASK_NAME:   task implementation id within the domain (e.g. "taxform_6_1")
      - VARIANT_NAME: one concrete runnable case (e.g. "variant_1" or "base")

    Paths use Windows backslash convention rooted at :pyattr:`data_root`
    (injected by the framework; see module docstring). Tasks do not set the
    root — they only declare DOMAIN/TASK/VARIANT and read the path properties.
    """

    # Name of the output subdirectory under task_dir (just the leaf name, not a
    # path). Overridable via the OUTPUT_SUBDIR env var; almost never changed.
    OUTPUT_SUBDIR: str = os.environ.get("OUTPUT_SUBDIR", "output")
    DOMAIN_NAME: str = ""
    TASK_NAME: str = ""
    VARIANT_NAME: str = ""
    OS_TYPE: str = os.environ.get("OS_TYPE", "windows")
    REQUIRES_TASK_DATA: bool = True

    @property
    def data_root(self) -> str:
        """VM-side data root, injected by the framework for this run unit.

        Raises if read before injection (rather than silently yielding a wrong
        path). The framework binds it via ``set_data_root`` after provisioning.
        """
        root = _DATA_ROOT.get()
        if root is None:
            raise RuntimeError(
                f"data_root not injected for "
                f"{self.DOMAIN_NAME}/{self.TASK_NAME}/{self.VARIANT_NAME}: a "
                "task path property was read before the framework bound a data "
                "root. set_data_root() must run (after VM provisioning) first."
            )
        return root

    @property
    def task_description(self) -> str:
        """Task description for the agent."""
        return ""

    @property
    def task_dir(self) -> str:
        """Generate task directory based on domain/task/variant."""
        return rf"{self.data_root}\{self.DOMAIN_NAME}\{self.TASK_NAME}\{self.VARIANT_NAME}"

    @property
    def input_dir(self) -> str:
        """Agent-visible input directory."""
        return rf"{self.task_dir}\input"

    @property
    def software_dir(self) -> str:
        """Generate software directory."""
        return rf"{self.task_dir}\software"

    @property
    def output_dir(self) -> str:
        """Agent-visible output directory (full path)."""
        return rf"{self.task_dir}\{self.OUTPUT_SUBDIR}"

    @property
    def reference_dir(self) -> str:
        """Reference directory."""
        return rf"{self.task_dir}\reference"

    @property
    def task_card_path(self) -> Path:
        """Operator-side path to this task's task_card.json."""
        return _TASKS_ROOT / self.DOMAIN_NAME / self.TASK_NAME / "task_card.json"

    @property
    def required_credentials(self) -> list[dict]:
        """Agent-side credentials this task needs at run time.

        Auto-derived from ``task_card.json``'s ``requiredCredentials`` field.
        Empty list when the task declares none. See
        ``docs/task_impl_guides/admin/stage1/07_CREDENTIALS_AND_LICENSES.md``
        for schema.
        """
        card = self.task_card_path
        if not card.exists():
            return []
        try:
            data = json.loads(card.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data.get("requiredCredentials") or []

    def to_metadata(self) -> dict:
        """Convert config to metadata dict for cua_bench Task."""
        meta = {
            "domain_name": self.DOMAIN_NAME,
            "task_name": self.TASK_NAME,
            "variant_name": self.VARIANT_NAME,
            "requires_task_data": self.REQUIRES_TASK_DATA,
            "task_dir": self.task_dir,
            "input_dir": self.input_dir,
            "software_dir": self.software_dir,
            "output_dir": self.output_dir,
            "reference_dir": self.reference_dir,
        }
        creds = self.required_credentials
        if creds:
            meta["required_credentials"] = creds
        return meta
