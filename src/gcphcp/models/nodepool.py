"""NodePool data models for GCP HCP CLI."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodePoolCondition(BaseModel):
    """Represents a nodepool condition."""

    type: str = Field(description="Type of condition")
    status: str = Field(description="Status of condition (True/False/Unknown)")
    lastTransitionTime: Optional[datetime] = Field(
        default=None, description="Last transition time"
    )
    reason: Optional[str] = Field(default=None, description="Reason for condition")
    message: Optional[str] = Field(default=None, description="Human-readable message")


class NodePoolStatus(BaseModel):
    """Nodepool status info (matches NodePoolStatusInfo from API spec)."""

    observedGeneration: Optional[int] = Field(
        default=None, description="Last generation processed by controllers"
    )
    conditions: List[NodePoolCondition] = Field(
        default_factory=list, description="Status conditions (Ready, Available)"
    )
    phase: Optional[str] = Field(default=None, description="High-level nodepool phase")
    message: Optional[str] = Field(
        default=None, description="Human-readable status message"
    )
    reason: Optional[str] = Field(
        default=None, description="Machine-readable reason code"
    )
    lastUpdateTime: Optional[datetime] = Field(
        default=None, description="When status was last calculated"
    )
    # Extra fields not in API spec but useful for display
    nodeCount: Optional[int] = Field(
        default=None, description="Current number of nodes"
    )
    readyNodeCount: Optional[int] = Field(
        default=None, description="Number of ready nodes"
    )


class NodePoolControllerStatus(BaseModel):
    """Represents individual controller status for a nodepool."""

    nodepool_id: str = Field(description="NodePool UUID")
    controller_name: str = Field(description="Controller name")
    observed_generation: Optional[int] = Field(
        default=None, description="Last generation processed by this controller"
    )
    conditions: List[NodePoolCondition] = Field(
        default_factory=list, description="Controller-specific conditions"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional controller metadata"
    )
    last_updated: Optional[datetime] = Field(
        default=None, description="When controller last updated status"
    )


class NodePoolManagement(BaseModel):
    """Represents nodepool management configuration."""

    autoRepair: Optional[bool] = Field(default=None, description="Enable auto-repair")
    autoUpgrade: Optional[bool] = Field(default=None, description="Enable auto-upgrade")
    upgradeType: Optional[str] = Field(
        default=None, description="Upgrade strategy type"
    )


class GCPRootVolume(BaseModel):
    """GCP root volume configuration."""

    size: Optional[int] = Field(default=None, description="Disk size in GB")
    type: Optional[str] = Field(default=None, description="Disk type")


class GCPNodePoolPlatform(BaseModel):
    """GCP-specific nodepool platform configuration."""

    instanceType: Optional[str] = Field(default=None, description="GCP instance type")
    rootVolume: Optional[GCPRootVolume] = Field(
        default=None, description="Root volume config"
    )
    labels: Optional[Dict[str, str]] = Field(default=None, description="Node labels")
    taints: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Node taints"
    )


class NodePoolPlatform(BaseModel):
    """Platform configuration for nodepool."""

    type: str = Field(description="Platform type (e.g., GCP)")
    gcp: Optional[GCPNodePoolPlatform] = Field(
        default=None, description="GCP configuration"
    )


class NodePoolSpec(BaseModel):
    """Represents nodepool specification."""

    clusterId: Optional[str] = Field(
        default=None, description="Parent cluster ID", alias="cluster_id"
    )
    replicas: Optional[int] = Field(default=None, description="Desired number of nodes")
    platform: Optional[NodePoolPlatform] = Field(
        default=None, description="Platform configuration"
    )
    management: Optional[NodePoolManagement] = Field(
        default=None, description="Management configuration"
    )

    # Backward compatibility - keep old fields
    machineType: Optional[str] = Field(
        default=None,
        description="GCP machine type (deprecated - use platform.gcp.instanceType)",
    )
    diskSize: Optional[int] = Field(
        default=None,
        description=(
            "Boot disk size in GB " "(deprecated - use platform.gcp.rootVolume.size)"
        ),
    )
    nodeCount: Optional[int] = Field(
        default=None, description="Desired number of nodes (deprecated - use replicas)"
    )
    minNodeCount: Optional[int] = Field(
        default=None, description="Minimum number of nodes"
    )
    maxNodeCount: Optional[int] = Field(
        default=None, description="Maximum number of nodes"
    )
    labels: Optional[Dict[str, str]] = Field(default=None, description="Node labels")
    taints: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Node taints"
    )

    def get_replicas(self) -> Optional[int]:
        """Get replicas count with backward compatibility.

        Returns:
            Replicas count from either replicas or nodeCount field
        """
        return self.replicas if self.replicas is not None else self.nodeCount

    def get_machine_type(self) -> Optional[str]:
        """Get machine type with backward compatibility.

        Returns:
            Machine type from platform.gcp.instanceType or machineType field
        """
        if self.platform and self.platform.gcp and self.platform.gcp.instanceType:
            return self.platform.gcp.instanceType
        return self.machineType

    def get_disk_size(self) -> Optional[int]:
        """Get disk size with backward compatibility.

        Returns:
            Disk size from platform.gcp.rootVolume.size or diskSize field
        """
        if (
            self.platform
            and self.platform.gcp
            and self.platform.gcp.rootVolume
            and self.platform.gcp.rootVolume.size
        ):
            return self.platform.gcp.rootVolume.size
        return self.diskSize

    def get_disk_type(self) -> Optional[str]:
        """Get disk type from platform configuration.

        Returns:
            Disk type from platform.gcp.rootVolume.type
        """
        if (
            self.platform
            and self.platform.gcp
            and self.platform.gcp.rootVolume
            and self.platform.gcp.rootVolume.type
        ):
            return self.platform.gcp.rootVolume.type
        return None

    class Config:
        """Pydantic configuration."""

        populate_by_name = True


class NodePool(BaseModel):
    """Represents a nodepool resource."""

    id: str = Field(description="Unique nodepool identifier")
    name: str = Field(description="NodePool name")
    clusterId: str = Field(description="Parent cluster ID", alias="cluster_id")
    createdBy: Optional[str] = Field(
        default=None, description="User who created the nodepool"
    )
    generation: Optional[int] = Field(default=None, description="Generation number")
    resourceVersion: Optional[str] = Field(default=None, description="Resource version")
    spec: Optional[NodePoolSpec] = Field(
        default=None, description="NodePool specification"
    )
    status: Optional[NodePoolStatus] = Field(
        default=None, description="NodePool status"
    )
    createdAt: Optional[datetime] = Field(
        default=None, description="Creation timestamp"
    )
    updatedAt: Optional[datetime] = Field(
        default=None, description="Last update timestamp"
    )

    class Config:
        """Pydantic configuration."""

        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
        }

    def get_display_status(self) -> str:
        """Get human-readable status.

        Returns:
            Status string for display
        """
        if self.status and self.status.phase:
            return self.status.phase
        return "Unknown"

    def is_ready(self) -> bool:
        """Check if nodepool is ready.

        Returns:
            True if nodepool is ready, False otherwise
        """
        return self.get_display_status() == "Ready"

    def get_node_info(self) -> str:
        """Get node count information.

        Returns:
            Node count string (e.g., "3/5 ready")
        """
        if not self.status:
            return "Unknown"

        ready_count = self.status.readyNodeCount or 0
        total_count = self.status.nodeCount or 0

        if total_count == 0:
            return "0 nodes"

        return f"{ready_count}/{total_count} ready"

    def get_age(self) -> str:
        """Get nodepool age as human-readable string.

        Returns:
            Age string (e.g., "2d", "5h", "30m")
        """
        if not self.createdAt:
            return "Unknown"

        now = datetime.now(self.createdAt.tzinfo)
        delta = now - self.createdAt

        if delta.days > 0:
            return f"{delta.days}d"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours}h"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes}m"
        else:
            return f"{delta.seconds}s"

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "NodePool":
        """Create nodepool from API response data.

        Args:
            data: API response data

        Returns:
            NodePool instance
        """
        # Handle datetime fields
        if "createdAt" in data and data["createdAt"]:
            data["createdAt"] = datetime.fromisoformat(
                data["createdAt"].replace("Z", "+00:00")
            )
        if "updatedAt" in data and data["updatedAt"]:
            data["updatedAt"] = datetime.fromisoformat(
                data["updatedAt"].replace("Z", "+00:00")
            )

        # Handle nested status
        if "status" in data and data["status"]:
            status_data = data["status"]
            if "conditions" in status_data:
                conditions = []
                for cond in status_data["conditions"]:
                    if "lastTransitionTime" in cond and cond["lastTransitionTime"]:
                        cond["lastTransitionTime"] = datetime.fromisoformat(
                            cond["lastTransitionTime"].replace("Z", "+00:00")
                        )
                    conditions.append(NodePoolCondition(**cond))
                status_data["conditions"] = conditions
            # Handle lastUpdateTime
            if "lastUpdateTime" in status_data and status_data["lastUpdateTime"]:
                status_data["lastUpdateTime"] = datetime.fromisoformat(
                    status_data["lastUpdateTime"].replace("Z", "+00:00")
                )
            data["status"] = NodePoolStatus(**status_data)

        # Handle spec
        if "spec" in data and data["spec"]:
            spec_data = data["spec"]

            # Handle management
            if "management" in spec_data and spec_data["management"]:
                spec_data["management"] = NodePoolManagement(**spec_data["management"])

            # Handle platform (nested structure)
            if "platform" in spec_data and spec_data["platform"]:
                platform_data = spec_data["platform"]
                if "gcp" in platform_data and platform_data["gcp"]:
                    gcp_data = platform_data["gcp"]
                    # Handle rootVolume
                    if "rootVolume" in gcp_data and gcp_data["rootVolume"]:
                        gcp_data["rootVolume"] = GCPRootVolume(**gcp_data["rootVolume"])
                    platform_data["gcp"] = GCPNodePoolPlatform(**gcp_data)
                spec_data["platform"] = NodePoolPlatform(**platform_data)

            data["spec"] = NodePoolSpec(**spec_data)

        return cls(**data)
