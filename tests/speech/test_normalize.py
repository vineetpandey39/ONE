"""Tests for conservative ONE transcript normalization."""

from openjarvis.speech.normalize import normalize_one_transcript


def test_normalizes_known_jarvis_check_in_mishearing():
    assert normalize_one_transcript("Jai Abhis, Arirabh") == "ONE, are you up?"


def test_normalizes_numbered_one_command_prefix():
    assert (
        normalize_one_transcript("1. Activate Athena and search my Obsidian memory.")
        == "ONE, Activate Athena and search my Obsidian memory."
    )


def test_does_not_rewrite_real_numbered_content():
    assert normalize_one_transcript("1. Revenue increased") == "1. Revenue increased"


def test_does_not_rewrite_names_in_longer_sentences():
    text = "Vineet met Jai Abhis yesterday to discuss the project"
    assert normalize_one_transcript(text) == text
