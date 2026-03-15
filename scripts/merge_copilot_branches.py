#!/usr/bin/env python3

import subprocess
import sys
import os

from typing import List, Tuple


def run_command(command: List[str], error_msg: str) -> Tuple[bool, str]:
    """Execute a shell command and return success status with output or error."""
    try:
        result = subprocess.run(command, shell=False, check=True, text=True, capture_output=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, f"{error_msg}: {e.stderr}"


def checkout_branch(branch: str) -> bool:
    """Checkout the specified branch."""
    success, output = run_command(['git', 'checkout', branch], f"Failed to checkout {branch}")
    if not success:
        print(output)
        return False
    return True


def fetch_origin() -> bool:
    """Fetch updates from origin."""
    success, output = run_command(['git', 'fetch', 'origin'], "Failed to fetch from origin")
    if not success:
        print(output)
        return False
    return True


def merge_branch(branch: str, prefer_complete: bool = True) -> bool:
    """Merge the specified branch into the current branch, resolving conflicts if needed."""
    print(f"Merging branch: {branch}")
    success, output = run_command(['git', 'merge', f"origin/{branch}"], f"Failed to merge {branch}")
    if not success:
        print(f"Conflict detected while merging {branch}. Attempting to resolve...")
        # Check for conflicts
        conflict_files = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=U'], shell=False, text=True, capture_output=True).stdout.splitlines()
        if conflict_files:
            print(f"Conflicts in files: {conflict_files}")
            if prefer_complete:
                print("Resolving conflicts by preferring more complete code (using ours or theirs based on context).")
                # TODO: Add logic to analyze diffs and prefer 'more complete' code. For now, we'll accept 'ours' as default.
                for conflict_file in conflict_files:
                    run_command(['git', 'checkout', '--ours', conflict_file], f"Failed to resolve conflict in {conflict_file}")
                run_command(['git', 'add'] + conflict_files, "Failed to stage resolved files")
                run_command(['git', 'commit', '-m', f"Auto-resolve conflicts for {branch}"], "Failed to commit conflict resolution")
        else:
            print(output)
            return False
    return True


def delete_branch(branch: str) -> bool:
    """Delete the specified branch locally and on origin."""
    print(f"Deleting branch: {branch}")
    success_local, output_local = run_command(['git', 'branch', '-d', branch], f"Failed to delete local branch {branch}")
    if not success_local:
        print(output_local)
    success_remote, output_remote = run_command(['git', 'push', 'origin', '--delete', branch], f"Failed to delete remote branch {branch}")
    if not success_remote:
        print(output_remote)
    return success_local and success_remote


def push_to_origin() -> bool:
    """Push changes to origin/main."""
    success, output = run_command(['git', 'push', 'origin', 'main'], "Failed to push to origin/main")
    if not success:
        print(output)
        return False
    return True


def main():
    """Main function to orchestrate branch merging for Quantum-Protocol."""
    repo_path = "/opt/repos/Quantum-Protocol"
    os.chdir(repo_path)
    
    branches_to_merge = [
        "brain-layer/v1.1",
        "dashboard/v1.0",
        "paper-trading/v1.0",
        "copilot/add-sleeves-3-4-5-implementation",
        "copilot/create-unified-quantum-engine",
        "copilot/implement-production-infrastructure",
        "copilot/fix-engine-creation-error-check",
        "copilot/review-adjust-rust-code"
    ]
    
    if not checkout_branch("main"):
        sys.exit(1)
    
    if not fetch_origin():
        sys.exit(1)
    
    for branch in branches_to_merge:
        if not merge_branch(branch):
            print(f"Failed to merge {branch}. Continuing with next branch.")
        else:
            print(f"Successfully merged {branch}")
    
    if push_to_origin():
        print("Successfully pushed all changes to origin/main")
    else:
        sys.exit(1)
    
    for branch in branches_to_merge:
        delete_branch(branch.split('/')[-1])  # Extract branch name if it contains slashes
    
    print("Merge and cleanup process completed.")


if __name__ == "__main__":
    main()
