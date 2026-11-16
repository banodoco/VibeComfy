"""Write transcription alignments as a managed ComfyUI output."""
from __future__ import annotations

import json
import os


class VibeComfySaveTranscript:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING",), "segments_alignment": ("whisper_alignment",),
                             "words_alignment": ("whisper_alignment",),
                             "filename_prefix": ("STRING", {"default": "transcript"})}}

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "vibecomfy/output"

    def save(self, text, segments_alignment, words_alignment, filename_prefix="transcript"):
        import folder_paths

        output_dir = folder_paths.get_output_directory()
        folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(filename_prefix, output_dir)
        name = f"{filename}_{counter:05}_.json"
        with open(os.path.join(folder, name), "x", encoding="utf-8") as stream:
            json.dump([text, segments_alignment, words_alignment], stream, ensure_ascii=False, allow_nan=False)
        return {"ui": {"images": [{"filename": name, "subfolder": subfolder, "type": "output"}]}}
