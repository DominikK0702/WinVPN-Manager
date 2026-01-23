from abc import ABC, abstractmethod
from typing import List

from core.models import OperationResult, VpnProfile, VpnProfileSpec


class VpnBackend(ABC):
    @abstractmethod
    def list_profiles(self, include_all_users: bool = False) -> List[VpnProfile]:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, name: str, all_users: bool = False) -> str:
        raise NotImplementedError

    @abstractmethod
    def connect(self, name: str, all_users: bool = False, timeout: int = 20) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self, name: str, all_users: bool = False, timeout: int = 20) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def connect_and_wait(
        self,
        name: str,
        all_users: bool = False,
        poll_interval: float = 1.0,
        max_wait: int = 20,
    ) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def create_profile(self, spec: VpnProfileSpec, all_users: bool = False) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def update_profile(
        self,
        name: str,
        spec: VpnProfileSpec,
        all_users: bool = False,
    ) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def delete_profile(self, name: str, all_users: bool = False) -> OperationResult:
        raise NotImplementedError
