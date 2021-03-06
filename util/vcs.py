from abc import ABCMeta, abstractmethod
import subprocess
import re
import os

from ..parser.file_diff import FileDiff


class VCSHelper(object):
    __metaclass__ = ABCMeta
    SVN_BASE_MATCH = re.compile('Root Path:\s*([\:\\\\/\w\.\-]*)')

    @classmethod
    def get_helper(cls, cwd):
        """Get the correct VCS helper for this codebase.

        Args:
            cwd: The current directory.  Not necessarily the base of the VCS.
        """
        # Check for a Git repo first
        try:
            p = subprocess.Popen(
                'git rev-parse --show-toplevel',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                cwd=cwd)
            out, err = p.communicate()
            if not err:
                return GitHelper(out.decode('utf-8').rstrip())
        except:
            pass

        try:
            # Now check for SVN
            p = subprocess.Popen(
                'svn info',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                cwd=cwd)
            out, err = p.communicate()
            if not err:
                match = VCSHelper.SVN_BASE_MATCH.search(out.decode('utf-8'))
                if match:
                    return SVNHelper(match.group(1))
                else:
                    print("Couldn't find SVN repo in:\n{}".format(
                        out.decode('utf-8')))
        except:
            pass

        # No VCS found
        raise NoVCSError

    @abstractmethod
    def get_changed_files(self, diff_args):
        """Get a list of changed files."""
        pass

    @abstractmethod
    def get_file_versions(self, diff_args):
        """Get both the versions of the file.

        This returns the 'version' for the old and new file, as it needs to be
        passed in to `get_file_content`.

        An empty string means that the file is the working copy version.

        Args:
            diff_args: The diff arguments.
        """
        pass

    @abstractmethod
    def get_file_content(self, filename, version):
        """Get the contents of a file at a specific version."""
        pass


class NoVCSError(Exception):
    """Exception raised when no VCS is found."""
    pass


class GitHelper(VCSHelper):

    STAT_CHANGED_FILE = re.compile('\s*([\w\.\-\/]+)\s*\|')
    DIFF_MATCH_MERGE_BASE = re.compile('(.*)\.\.\.(.*)')
    DIFF_MATCH = re.compile('(.*)\.\.(.*)')
    """VCSHelper implementation for Git repositories."""

    def __init__(self, repo_base):
        self.git_base = repo_base
        self.got_changed_files = False

    def get_changed_files(self, diff_args):
        files = []
        if not self.got_changed_files:
            diff_stat = self.git_command(['diff', '--stat', diff_args])
            for line in diff_stat.split('\n'):
                match = self.STAT_CHANGED_FILE.match(line)
                if match:
                    filename = match.group(1)
                    abs_filename = os.path.join(self.git_base, filename)

                    # Get the diff text for this file.
                    diff_text = self.git_command(
                        ['diff',
                         diff_args,
                         '-U0',
                         '--',
                         filename])
                    files.append(FileDiff(filename, abs_filename, diff_text))
        self.got_changed_files = True
        return files

    def get_file_versions(self, diff_args):
        # Merge base diff
        match = self.DIFF_MATCH_MERGE_BASE.match(diff_args)
        if match:
            merge_base = self.git_command(
                ['merge_base',
                 match.group(1),
                 match.group(2)])
            return (merge_base, match.group(2))

        # Normal diff
        match = self.DIFF_MATCH.match(diff_args)
        if match:
            return (match.group(1), match.group(2))

        if diff_args != '':
            # WC comparison
            return (diff_args, '')

        # HEAD to WC comparison
        return ('HEAD', '')

    def get_file_content(self, filename, version):
        git_args = ['show', '{}:{}'.format(version, filename)]
        try:
            content = self.git_command(git_args)
        except UnicodeDecodeError:
            content = "Unable to decode file..."
        return content

    def git_command(self, args):
        """Wrapper to run a Git command."""
        # Using shell, just pass a string to subprocess.
        p = subprocess.Popen(" ".join(['git'] + args),
                             stdout=subprocess.PIPE,
                             shell=True,
                             cwd=self.git_base)
        out, err = p.communicate()
        return out.decode('utf-8')


class SVNHelper(VCSHelper):

    STATUS_CHANGED_FILE = re.compile('\s*[AM][\+CMLSKOTB\s]*([\w\.\-\/\\\\]+)')
    DUAL_REV_MATCH = re.compile('-r *(\d+):(\d+)')
    REV_MATCH = re.compile('-r *(\d+)')
    COMMIT_MATCH = re.compile('-c *(\d+)')
    """VCSHelper implementation for SVN repositories."""

    def __init__(self, repo_base):
        self.svn_base = repo_base
        self.got_changed_files = False

    def get_changed_files(self, diff_args):
        files = []
        if not self.got_changed_files:
            if self.DUAL_REV_MATCH.match(diff_args):
                # Comparison between 2 revisions
                status_text = self.svn_command(
                    ['diff', diff_args, '--summarize'])
            elif self.REV_MATCH.match(diff_args):
                # Can only compare this against HEAD
                status_text = self.svn_command(
                    ['diff', diff_args + ":HEAD", '--summarize'])
            elif self.COMMIT_MATCH.match(diff_args):
                # Commit match
                status_text = self.svn_command(
                    ['diff', diff_args, '--summarize'])
            else:
                # Show uncommitted changes
                status_text = self.svn_command(['status', diff_args])
            for line in status_text.split('\n'):
                match = self.STATUS_CHANGED_FILE.match(line)
                if match:
                    filename = match.group(1)
                    abs_filename = os.path.join(self.svn_base, filename)

                    # Don't add directories to the list
                    if not os.path.isdir(abs_filename):
                        # Get the diff text for this file.
                        diff_text = self.svn_command(
                            ['diff', diff_args, filename])
                        files.append(FileDiff(
                            filename,
                            abs_filename,
                            diff_text))

        self.got_changed_files = True
        return files

    def get_file_versions(self, diff_args):
        # Diff between two versions?
        match = self.DUAL_REV_MATCH.match(diff_args)
        if match:
            return (
                '-r {}'.format(match.group(1)),
                '-r {}'.format(match.group(2)))

        # Diff HEAD against a specific revision?
        match = self.REV_MATCH.match(diff_args)
        if match:
            return ('-r {}'.format(match.group(1)), '-r HEAD')

        # Diff for a specific commit
        match = self.COMMIT_MATCH.match(diff_args)
        if match:
            new_revision = int(match.group(1))
            old_revision = new_revision - 1
            return ('-r {}'.format(old_revision), '-r {}'.format(new_revision))

        # Compare HEAD against WC
        return ('-r HEAD', '')

    def get_file_content(self, filename, version):
        try:
            content = self.svn_command(['cat', version, filename])
        except UnicodeDecodeError:
            content = "Unable to decode file..."
        return content

    def svn_command(self, args):
        """Wrapper to run an SVN command."""
        # Using shell, just pass a string to subprocess.
        p = subprocess.Popen(" ".join(['svn'] + args),
                             stdout=subprocess.PIPE,
                             shell=True,
                             cwd=self.svn_base)
        out, err = p.communicate()
        return out.decode('utf-8')
