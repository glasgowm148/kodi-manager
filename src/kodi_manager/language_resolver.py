import os
import re


class LanguageResolver:
    def __init__(self, addon_path=None):
        self.labels = {}
        if addon_path:
            self.load_from_addon(addon_path)

    def load_from_addon(self, addon_path):
        direct = os.path.join(addon_path, "strings.po")
        if os.path.exists(direct):
            self.load_po(direct)
        lang_root = os.path.join(addon_path, "resources", "language")
        if not os.path.isdir(lang_root):
            return
        for root, _, files in os.walk(lang_root):
            if "strings.po" in files:
                self.load_po(os.path.join(root, "strings.po"))

    def load_po(self, path):
        if not os.path.exists(path):
            return
        current = None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r'msgctxt "#(\d+)"', line.strip())
                if m:
                    current = m.group(1)
                    continue
                if current and line.startswith("msgid "):
                    val = line[6:].strip()
                    if val.startswith('"') and val.endswith('"'):
                        self.labels[current] = val[1:-1]
                    current = None

    def resolve(self, label):
        text = str(label or "")
        if text.isdigit():
            return self.labels.get(text, "Label %s" % text)
        return text
