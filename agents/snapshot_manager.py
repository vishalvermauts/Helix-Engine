import os
import shutil
import time
from lib.logging import get_logger

logger = get_logger("snapshot_manager")

class SnapshotManager:
    def __init__(self, workspace_dir: str = "/workspaces/AirCode/workspace", backup_dir: str = "/workspaces/AirCode/backup_snapshots"):
        self.workspace_dir = workspace_dir
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_snapshot(self) -> str:
        """
        Creates a full backup of the workspace directory before Aider mutates it.
        Returns the path to the backup folder.
        """
        if not os.path.exists(self.workspace_dir):
            return ""

        timestamp = str(int(time.time()))
        snapshot_path = os.path.join(self.backup_dir, f"snapshot_{timestamp}")
        
        try:
            shutil.copytree(self.workspace_dir, snapshot_path)
            logger.info(f"📸 Workspace snapshot created at: {snapshot_path}")
            return snapshot_path
        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            return ""

    def rollback_snapshot(self, snapshot_path: str) -> bool:
        """
        Instantly restores the workspace to the exact state of the provided snapshot_path.
        """
        if not snapshot_path or not os.path.exists(snapshot_path):
            logger.error("Rollback failed: Snapshot path invalid or missing.")
            return False
            
        try:
            # Wipe current workspace
            if os.path.exists(self.workspace_dir):
                shutil.rmtree(self.workspace_dir)
                
            # Restore from snapshot
            shutil.copytree(snapshot_path, self.workspace_dir)
            logger.warning(f"⏪ Workspace completely rolled back to snapshot: {snapshot_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to rollback snapshot: {e}")
            return False

def get_snapshot_manager() -> SnapshotManager:
    return SnapshotManager()
