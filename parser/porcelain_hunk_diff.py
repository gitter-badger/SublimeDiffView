import re
import sublime

from .diff_region import DiffRegion


class HunkDiff(object):

    NEWLINE_MATCH = re.compile('\r?\n')
    ADD_LINE_MATCH = re.compile('^\+(.*)')
    DEL_LINE_MATCH = re.compile('^\-(.*)')
    """Representation of a single 'hunk' from a Git diff.

    Args:
        file_diff: The parent `FileDiff` object.
        match: The match parts of the hunk header.
    """

    def __init__(self, file_diff, match):
        self.file_diff = file_diff
        self.old_regions = []
        self.new_regions = []
        self.concise_description = False

        # Matches' meanings are:
        # - 0: start line in old file
        self.old_line_start = int(match[0])
        # - 1: num lines removed from old file (0 for ADD, missing if it's a
        #      one-line change)
        self.old_hunk_len = 1
        if len(match[1]) > 0:
            self.old_hunk_len = int(match[1])
        # - 2: start line in new file
        self.new_line_start = int(match[2])
        # - 3: num lines added to new file (0 for DEL, missing if it's a
        #      one-line change)
        self.new_hunk_len = 1
        if len(match[3]) > 0:
            self.new_hunk_len = int(match[3])
        # - 4: the remainder of the hunk, after the header
        self.context = self.NEWLINE_MATCH.split(match[4])[0]
        self.hunk_diff_lines = self.NEWLINE_MATCH.split(match[4])[1:]

        if self.old_hunk_len == 0:
            self.hunk_type = "ADD"
        elif self.new_hunk_len == 0:
            self.hunk_type = "DEL"
        else:
            self.hunk_type = "MOD"

        # Create the description that will appear in the quick_panel.
        if self.concise_description:
            self.description = "{}:{}".format(
                file_diff.filename,
                self.new_line_start)
        else:
            self.description = [
                "{} : {}".format(file_diff.filename, self.new_line_start),
                self.context,
                "{} | {}{}".format(self.old_hunk_len + self.new_hunk_len,
                                   "+" * self.new_hunk_len,
                                   "-" * self.old_hunk_len)]

    def parse_diff(self):
        """Generate representations of the changed regions."""
        # ADD and DEL are easy.
        if self.hunk_type == "ADD":
            self.old_regions.append(DiffRegion(
                "DEL",
                self.old_line_start,
                0,
                self.old_line_start + self.old_hunk_len,
                0))
            self.new_regions.append(DiffRegion(
                "ADD",
                self.new_line_start,
                0,
                self.new_line_start + self.new_hunk_len,
                0))
        elif self.hunk_type == "DEL":
            self.old_regions.append(DiffRegion(
                "ADD",
                self.old_line_start,
                0,
                self.old_line_start + self.old_hunk_len,
                0))
            self.new_regions.append(DiffRegion(
                "DEL",
                self.new_line_start,
                0,
                self.new_line_start + self.new_hunk_len,
                0))
        else:
            old_cur_line = self.old_line_start
            new_cur_line = self.new_line_start
            old_add_line = 0
            new_add_start = 0
            old_del_start = 0
            new_del_line = 0
            in_add = False
            in_del = False

            for line in self.hunk_diff_lines:
                if line.startswith(' '):
                    if in_add:
                        # ADD region ends.
                        self.new_regions.append(DiffRegion(
                            "ADD",
                            new_add_start,
                            0,
                            new_cur_line,
                            0))
                        # Add a blank DEL region to the old regions.
                        self.old_regions.append(DiffRegion(
                            "DEL",
                            old_add_line,
                            0,
                            old_add_line,
                            0))
                        in_add = False
                    if in_del:
                        # DEL region ends.
                        self.old_regions.append(DiffRegion(
                            "DEL",
                            old_del_start,
                            0,
                            old_cur_line,
                            0))
                        # Add a blank ADD region to the old regions.
                        self.new_regions.append(DiffRegion(
                            "ADD",
                            new_del_line,
                            0,
                            new_del_line,
                            0))
                        in_del = False
                elif line.startswith('+'):
                    if not in_add:
                        new_add_start = new_cur_line
                        old_add_line = old_cur_line
                        in_add = True
                elif line.startswith('-'):
                    if not in_del:
                        new_del_line = new_cur_line
                        old_del_start = old_cur_line
                        in_del = True
                else:
                    print("Unexpected line: {} in {}".format(line))

                # End of that line.
                old_cur_line += 1
                new_cur_line += 1

    def sort_chunks(self):
        """Sort the sub-chunks in this hunk into those which are interesting
        for ADD regions, and those that are interesting for DEL regions.

        Returns:
            (add_chunks, del_chunks)
        """
        add_chunks = []
        del_chunks = []
        cur_chunk = []
        cur_chunk_has_del = False
        cur_chunk_has_add = False
        need_newline = False

        # ADD chunks
        for line in self.hunk_diff_lines:
            if line.startswith('~'):
                if need_newline or not cur_chunk_has_del:
                    add_chunks.append(cur_chunk)
                    cur_chunk = []
                    cur_chunk_has_del = False
                    need_newline = False
            elif line.startswith('-'):
                cur_chunk_has_del = True
            else:
                cur_chunk.append(line)
                if line.startswith('+'):
                    need_newline = True

        # DEL chunks
        cur_chunk = []
        for line in self.hunk_diff_lines:
            if line.startswith('~'):
                if need_newline or not cur_chunk_has_add:
                    del_chunks.append(cur_chunk)
                    cur_chunk = []
                    cur_chunk_has_add = False
                    need_newline = False
            elif line.startswith('+'):
                cur_chunk_has_add = True
            else:
                cur_chunk.append(line)
                if line.startswith('-'):
                    need_newline = True

        return (add_chunks, del_chunks)

    def filespecs(self):
        """Get the portion of code that this hunk refers to in the format
        `(old_filename:old_line, new_filename:new_line`.
        """
        old_filespec = "{}:{}".format(
            self.file_diff.old_file,
            self.old_line_start)
        new_filespec = "{}:{}".format(
            self.file_diff.abs_filename,
            self.new_line_start)
        return (old_filespec, new_filespec)

    def get_old_regions(self, view):
        """Create a `sublime.Region` for each (old) part of this hunk."""
        if not self.old_regions:
            self.parse_diff()
        return [sublime.Region(
            view.text_point(r.start_line - 1, r.start_col),
            view.text_point(r.end_line - 1, r.end_col))
            for r in self.old_regions]

    def get_new_regions(self, view):
        """Create a `sublime.Region` for each (new) part of this hunk."""
        if not self.new_regions:
            self.parse_diff()
        return [sublime.Region(
            view.text_point(r.start_line - 1, r.start_col),
            view.text_point(r.end_line - 1, r.end_col))
            for r in self.new_regions]