from unittest.mock import MagicMock, patch

from src.services.ingestion import HybridIngestionService


@patch("src.services.ingestion._fetch_captions_via_timedtext")
def test_hybrid_uses_captions_when_available(mock_captions):
    mock_captions.return_value = "This is a sponsored video."
    service = HybridIngestionService()
    result = service.enrich("https://youtu.be/dT7S75eYhcQ", "Title: Demo")
    assert result["ingestion_source"] == "captions"
    assert "sponsored" in result["transcript"].lower()


@patch("src.services.ingestion._fetch_captions_via_timedtext", return_value=None)
@patch("src.services.ingestion._fetch_captions_via_ytdlp", return_value=None)
def test_hybrid_falls_back_to_metadata(mock_ytdlp, mock_timedtext):
    service = HybridIngestionService()
    with patch.object(HybridIngestionService, "enrich", wraps=service.enrich):
        with patch("src.services.ingestion.VideoIndexerService") as vi_cls:
            vi_cls.return_value.account_id = None
            result = service.enrich("https://youtu.be/dT7S75eYhcQ", "Title: Demo")
    assert result["ingestion_source"] == "metadata"
