from datetime import UTC, datetime

import pytest

from tests.conftest import load_uk
from travel_risk.ingestion import uk_fcdo, us_state
from travel_risk.ingestion.snapshot import Source, html_to_text


class TestUSFeed:
    def test_parses_every_item(self, us_feed_xml):
        snaps = us_state.parse_feed(us_feed_xml)
        # Every item except the legacy "French West Indies" aggregate (covered per territory).
        assert len(snaps) == us_feed_xml.count(b"<item>") - 1
        assert {"GP", "MQ", "MF", "BL"} <= {s.country_iso for s in snaps}
        assert all(s.source is Source.US_STATE for s in snaps)
        assert all(1 <= s.level <= 4 for s in snaps)

    def test_legacy_url_falls_back_to_fips(self, us_feed_xml):
        to = next(s for s in us_state.parse_feed(us_feed_xml) if s.title.startswith("Tonga"))
        assert to.country_iso == "TO"

    def test_lebanon(self, us_feed_xml):
        lb = next(s for s in us_state.parse_feed(us_feed_xml) if s.country_iso == "LB")
        assert lb.level == 4
        assert lb.source_level_label == "Level 4: Do Not Travel"
        assert lb.title.startswith("Lebanon")
        assert "<" not in lb.summary
        assert lb.source_updated_at is not None and lb.source_updated_at.tzinfo is not None

    def test_iran_date(self, us_feed_xml):
        ir = next(s for s in us_state.parse_feed(us_feed_xml) if s.country_iso == "IR")
        assert ir.source_updated_at == datetime(2026, 10, 23, tzinfo=UTC)

    def test_gaza_and_west_bank_both_map_to_ps(self, us_feed_xml):
        ps = [s for s in us_state.parse_feed(us_feed_xml) if s.country_iso == "PS"]
        assert {s.level for s in ps} == {3, 4}

    def test_level_4_is_never_regional(self, us_feed_xml):
        assert not any(s.regional for s in us_state.parse_feed(us_feed_xml) if s.level == 4)

    def test_bad_item_is_skipped_not_fatal(self):
        xml = b"""<rss><channel>
          <item><title>Nowhere - Level 2: Exercise Increased Caution</title>
                <link>https://x/destination.zzz.html</link></item>
          <item><title>France - Level 2: Exercise Increased Caution</title>
                <link>https://x/destination.fra.html</link><pubDate>Fri, 23 Oct 2026</pubDate>
                <description>&lt;p&gt;Be careful&lt;/p&gt;</description></item>
        </channel></rss>"""
        snaps = us_state.parse_feed(xml)
        assert [s.country_iso for s in snaps] == ["FR"]
        assert snaps[0].summary == "Be careful"


class TestUKFeed:
    def test_index(self, uk_index):
        entries = uk_fcdo.parse_index(uk_index)
        assert len(entries) == len(uk_index["links"]["children"])
        assert all(e.public_updated_at.tzinfo is not None for e in entries)

    @pytest.mark.parametrize(
        ("name", "iso", "level", "regional"),
        [("iran", "IR", 4, False), ("lebanon", "LB", 3, True), ("france", "FR", 1, False)],
    )
    def test_country_pages(self, name, iso, level, regional):
        snap = uk_fcdo.parse_country(load_uk(name))
        assert (snap.country_iso, snap.level, snap.regional) == (iso, level, regional)
        assert snap.source is Source.UK_FCDO
        assert snap.source_updated_at is not None

    def test_lebanon_summary_has_restricted_areas_as_text(self):
        snap = uk_fcdo.parse_country(load_uk("lebanon"))
        assert "Haret Hraik" in snap.summary
        assert "<p>" not in snap.summary
        assert snap.summary.startswith("## Warnings and insurance")

    def test_index_and_page_agree_on_public_updated_at(self, uk_index):
        """Sync skips a country page when the index date equals the stored page date."""
        entries = {e.slug: e for e in uk_fcdo.parse_index(uk_index)}
        for name in ("iran", "lebanon", "france"):
            page = uk_fcdo.parse_country(load_uk(name))
            assert entries[name].public_updated_at == page.source_updated_at

    @pytest.mark.parametrize(
        ("statuses", "expected"),
        [
            ([], (1, False)),
            (["avoid_all_but_essential_travel_to_parts"], (2, True)),
            (["avoid_all_travel_to_parts"], (3, True)),
            (["avoid_all_but_essential_travel_to_whole_country"], (3, False)),
            (["avoid_all_travel_to_whole_country"], (4, False)),
            (["avoid_all_travel_to_parts", "avoid_all_but_essential_travel_to_whole_country"],
             (3, True)),
            (["something_new_from_fcdo"], (1, False)),
        ],
    )
    def test_level_mapping(self, statuses, expected):
        level, regional, _ = uk_fcdo.level_from_alert_status(statuses)
        assert (level, regional) == expected


def test_html_to_text():
    raw = "<p>Do not travel&nbsp;to <b>X</b>.</p><ul><li>One</li><li>Two &amp; three</li></ul>"
    assert html_to_text(raw) == "Do not travel to X.\n\nOne\n\nTwo & three"
