from __future__ import annotations
import logging
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
logger = logging.getLogger("services.llm_service")

_INDONESIAN_WEEKDAYS = (
    "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu",
)

_INDONESIAN_MONTHS = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)

class TemporalContext:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    @lru_cache(maxsize=8)
    def resolve_timezone(self, timezone_name: str) -> tuple[ZoneInfo | timezone, str]:
        """Resolve an IANA timezone, falling back safely when configuration is invalid."""
        try:
            return ZoneInfo(timezone_name), timezone_name
        except (ZoneInfoNotFoundError, ValueError):
            logger.error("Unknown USER_TIMEZONE %r; falling back to UTC", timezone_name)
            return timezone.utc, "UTC"

    def current_temporal_context(self,
        now: datetime | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, str | int]:
        """Return fresh, explicit clock data for one LLM request."""
        configured_timezone = timezone_name or self.config.USER_TIMEZONE
        user_timezone, resolved_timezone = self.resolve_timezone(configured_timezone)
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        local_now = instant.astimezone(user_timezone)

        offset = local_now.utcoffset()
        total_offset_minutes = int(offset.total_seconds() // 60) if offset else 0
        offset_sign = "+" if total_offset_minutes >= 0 else "-"
        offset_hours, offset_minutes = divmod(abs(total_offset_minutes), 60)
        utc_offset = f"UTC{offset_sign}{offset_hours:02d}:{offset_minutes:02d}"
        timezone_abbreviation = local_now.tzname() or resolved_timezone
        weekday = _INDONESIAN_WEEKDAYS[local_now.weekday()]
        month = _INDONESIAN_MONTHS[local_now.month - 1]

        return {
            "local_datetime_iso": local_now.isoformat(timespec="seconds"),
            "local_datetime_human": (
                f"{weekday}, {local_now.day} {month} {local_now.year}, "
                f"pukul {local_now:%H:%M:%S} {timezone_abbreviation}"
            ),
            "date_iso": local_now.date().isoformat(),
            "time_24h": local_now.strftime("%H:%M:%S"),
            "weekday": weekday,
            "current_year": local_now.year,
            "timezone": resolved_timezone,
            "timezone_abbreviation": timezone_abbreviation,
            "utc_offset": utc_offset,
        }

    def temporal_prompt_section(self, now: datetime | None = None) -> str:
        """Build authoritative temporal grounding shared by chat and memory extraction."""
        temporal_json = self.safe_context_json(self.current_temporal_context(now=now))
        return f"""KONTEKS WAKTU AKTUAL (SUMBER KEBENARAN UNTUK TURN INI):
<current_datetime_json>
{temporal_json}
</current_datetime_json>

ATURAN KESADARAN WAKTU:
- Perlakukan nilai di <current_datetime_json> sebagai waktu sekarang yang otoritatif. Jangan menebak tahun sekarang dari data latih, knowledge cutoff, atau riwayat percakapan.
- Semua kata relatif seperti hari ini, besok, kemarin, minggu depan, bulan depan, tahun ini, dan tahun depan WAJIB dihitung dari tanggal tersebut dalam zona waktu pengguna.
- Saat membandingkan tanggal, hitung dari tanggal lengkap bila tersedia. Tahun yang sama dengan current_year berarti tahun ini, bukan otomatis masih beberapa tahun lagi.
- Jika hanya tahun yang diketahui, jangan mengarang bulan/tanggal atau memastikan sudah lewat/belum lewat; jelaskan dengan presisi yang tersedia.
- Jika user menyatakan sebuah tanggal atau tahun sebagai fakta, tanggapi menggunakan acuan waktu ini. Bedakan klaim user dari fakta eksternal yang belum terverifikasi.
- Jangan menyebutkan jam/tanggal sekarang jika tidak relevan dengan jawaban."""
