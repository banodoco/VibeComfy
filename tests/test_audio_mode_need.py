"""WS-0a: stable, narrowly scoped code for unnamed audio modes."""
from vibecomfy.entries import draft_entry
from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource


def test_raw_audio_mode_need_is_coded_without_relabeling_other_ambiguities():
    graph = VibeWorkflow("audio", WorkflowSource("audio"))
    graph.nodes["1"] = VibeNode("1", "LoadAudio", inputs={"audio": "input.wav"})
    graph.nodes["2"] = VibeNode("2", "SaveAudio", inputs={"filename_prefix": "out"})
    ambiguity = {"audio": [{"node": "1", "field": "audio"}, {"node": "3", "field": "audio"}]}
    entry = draft_entry(graph, "audio", input_ambiguities=ambiguity)
    assert entry["kind"] == "audio" and entry["modes"] == []
    mode_need, input_need = entry["needs"]
    assert mode_need["code"] == "audio_mode_unknown"
    assert mode_need["role"] is None and mode_need["ambiguity"]
    assert input_need["ambiguity"] == "multiple targets for audio"
    assert input_need["candidates"] == ambiguity["audio"]
    assert input_need.get("code") != "audio_mode_unknown"


def test_transcribe_does_not_get_unknown_audio_mode_need():
    graph = VibeWorkflow("transcribe", WorkflowSource("transcribe"))
    graph.nodes["1"] = VibeNode("1", "VibeComfySaveTranscript")
    entry = draft_entry(graph, "transcribe")
    assert entry["modes"] == ["transcribe"]
    assert all(need.get("code") != "audio_mode_unknown" for need in entry["needs"])
