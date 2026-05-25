"""Provider implementations for VM lifecycle.

``Provider`` ABC + ``SandboxSpec`` + ``SandboxHandle`` + ``ReleaseMode`` live in
:mod:`ale_run.base_interface`; this package only holds the backends:

  - :class:`GcloudProvider` (``gcloud.py``): ephemeral GCE VMs.
  - :class:`StaticProvider` (``static.py``): a pre-existing VM endpoint.
"""

from ...base_interface import SandboxSpec, Provider, ReleaseMode, SandboxHandle
from .gcloud import GcloudProvider, GcloudProviderConfig
from .static import StaticProvider, StaticProviderConfig

__all__ = [
    "SandboxSpec",
    "GcloudProvider",
    "GcloudProviderConfig",
    "Provider",
    "ReleaseMode",
    "StaticProvider",
    "StaticProviderConfig",
    "SandboxHandle",
]
