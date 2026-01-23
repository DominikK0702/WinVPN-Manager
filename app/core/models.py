from dataclasses import dataclass


@dataclass
class VpnProfile:
    name: str
    server_address: str
    tunnel_type: str
    authentication_method: str
    connection_status: str
    all_users: bool = False


@dataclass
class VpnProfileSpec:
    name: str
    server_address: str
    tunnel_type: str


@dataclass
class OperationResult:
    success: bool
    message: str
    status: str = ""
    details: str = ""
