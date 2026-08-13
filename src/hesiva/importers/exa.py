import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import BinaryIO


HEADER_LIMIT = 64 * 1024
FILE_COUNT_LIMIT = 128
PATH_LIMIT = 4096
COMPRESSED_CHUNK_LIMIT = 64 * 1024 * 1024
DECOMPRESSED_CHUNK_LIMIT = 64 * 1024 * 1024
MEMBER_SIZE_LIMIT = 16 * 1024 * 1024 * 1024
AGGREGATE_MEMBER_SIZE_LIMIT = MEMBER_SIZE_LIMIT
AGGREGATE_COMPRESSED_SIZE_LIMIT = AGGREGATE_MEMBER_SIZE_LIMIT + 256 * 1024 * 1024
COMPRESSED_RECORD_COUNT_LIMIT = 1_000_000
# Leave generous room for the bounded header, file list, paths, record framing,
# and footer beyond the aggregate compressed payload. The caller applies this
# to the complete selected EXA before hashing it.
EXA_SOURCE_SIZE_LIMIT = AGGREGATE_COMPRESSED_SIZE_LIMIT + 64 * 1024 * 1024
FILE_LIST_SIZE_LIMIT = FILE_COUNT_LIMIT * (PATH_LIMIT + 64)
DECLARED_SIZE_DIGIT_LIMIT = len(str(MEMBER_SIZE_LIMIT))
FILE_LIST_NAME = b"FILE:LIST"
RECORD_MARKER = b"XEC2"
RECORD_METADATA_SIZE = 3
FOOTER = bytes(8)


class ExaFormatError(Exception):
    """Raised when an EXA source does not match the supported V1 profile."""


@dataclass(frozen=True, slots=True)
class _ListedMember:
    path_bytes: bytes
    declared_size: int


@dataclass(slots=True)
class _RecordBudget:
    compressed_size: int = 0
    record_count: int = 0

    def consume(self, compressed_size: int) -> None:
        self.compressed_size += compressed_size
        self.record_count += 1
        if self.compressed_size > AGGREGATE_COMPRESSED_SIZE_LIMIT:
            raise ExaFormatError("The EXA source exceeds the aggregate compressed-size limit.")
        if self.record_count > COMPRESSED_RECORD_COUNT_LIMIT:
            raise ExaFormatError("The EXA source contains too many compressed records.")


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    if size < 0:
        raise ExaFormatError("The EXA source contains an invalid length.")
    value = stream.read(size)
    if len(value) != size:
        raise ExaFormatError("The EXA source is truncated.")
    return value


def _read_uint32(stream: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(stream, 4))[0]


def _read_zlib_record(
    stream: BinaryIO,
    *,
    output_limit: int,
    budget: _RecordBudget,
) -> bytes:
    compressed_size = _read_uint32(stream)
    if compressed_size == 0 or compressed_size > COMPRESSED_CHUNK_LIMIT:
        raise ExaFormatError("The EXA source contains an unsupported compressed record.")
    budget.consume(compressed_size)
    compressed = _read_exact(stream, compressed_size)
    decompressor = zlib.decompressobj()
    try:
        value = decompressor.decompress(compressed, output_limit + 1)
        if len(value) > output_limit or decompressor.unconsumed_tail:
            raise ExaFormatError("The EXA compressed record exceeds its allowed size.")
        value += decompressor.flush()
    except zlib.error as error:
        raise ExaFormatError("The EXA source contains a corrupt compressed record.") from error
    if len(value) > output_limit:
        raise ExaFormatError("The EXA compressed record exceeds its allowed size.")
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ExaFormatError("The EXA source contains an invalid compressed record.")
    return value


def _read_record_header(stream: BinaryIO) -> None:
    _read_exact(stream, RECORD_METADATA_SIZE)
    if _read_exact(stream, len(RECORD_MARKER)) != RECORD_MARKER:
        raise ExaFormatError("The EXA source contains an unsupported record marker.")
    if _read_exact(stream, 1) != b"\x00":
        raise ExaFormatError("The EXA source uses an unsupported encoding profile.")


def _parse_file_list(payload: bytes, expected_count: int) -> tuple[_ListedMember, ...]:
    members: list[_ListedMember] = []
    for line in payload.splitlines():
        match = re.fullmatch(rb"(.+[.]edb)\t[0-9]+=([0-9]+)", line, re.IGNORECASE)
        if match is None:
            raise ExaFormatError("The EXA file list has an unsupported structure.")
        declared_size_bytes = match.group(2)
        if len(declared_size_bytes) > DECLARED_SIZE_DIGIT_LIMIT:
            raise ExaFormatError("The EXA file list contains an unsupported member size.")
        try:
            declared_size = int(declared_size_bytes)
        except ValueError as error:
            raise ExaFormatError(
                "The EXA file list contains an unsupported member size."
            ) from error
        if declared_size <= 0 or declared_size > MEMBER_SIZE_LIMIT:
            raise ExaFormatError("The EXA file list contains an unsupported member size.")
        members.append(_ListedMember(match.group(1), declared_size))
    if len(members) != expected_count:
        raise ExaFormatError("The EXA file count is inconsistent.")
    return tuple(members)


def _member_basename(path_bytes: bytes) -> str:
    try:
        decoded_path = path_bytes.decode("cp1254")
    except UnicodeDecodeError as error:
        raise ExaFormatError("An EXA member path is not valid Windows-1254 text.") from error
    return PureWindowsPath(decoded_path).name


def _remove_recovered_target(target_path: Path, primary_error: BaseException) -> None:
    """Best-effort private cleanup without replacing the parser's primary error."""
    try:
        target_path.unlink(missing_ok=True)
    except OSError as cleanup_error:
        primary_error.add_note(
            "The private recovered database could not be removed after failure: "
            f"{type(cleanup_error).__name__}."
        )


def recover_frm1_database(source_path: Path, destination_directory: Path) -> Path:
    """Recover exactly one validated Frm1.edb into a private temporary directory."""
    source = source_path.expanduser()
    if not source.is_file():
        raise ExaFormatError("The selected Veresiye 5 backup does not exist.")
    destination = destination_directory.expanduser()
    if not destination.is_dir():
        raise ExaFormatError("The private extraction directory is unavailable.")
    destination.chmod(0o700)

    target_path = destination / "Frm1.edb"
    candidate_count = 0
    target_created = False
    record_budget = _RecordBudget()
    try:
        with source.open("rb") as stream:
            header_size = _read_uint32(stream)
            if header_size == 0 or header_size > HEADER_LIMIT:
                raise ExaFormatError("The EXA source has an unsupported header length.")
            header = _read_exact(stream, header_size)
            try:
                header_text = header.decode("cp1254")
            except UnicodeDecodeError as error:
                raise ExaFormatError("The EXA header is not valid Windows-1254 text.") from error
            if "EXABilişim Yedek Dosyası" not in header_text or "Veresiye 5" not in header_text:
                raise ExaFormatError("The selected file is not a supported Veresiye 5 EXA backup.")

            _read_uint32(stream)  # Observed profile header metadata/checksum.
            file_count = _read_uint32(stream)
            if file_count == 0 or file_count > FILE_COUNT_LIMIT:
                raise ExaFormatError("The EXA source has an unsupported member count.")
            list_name_size = _read_uint32(stream)
            if list_name_size != len(FILE_LIST_NAME):
                raise ExaFormatError("The EXA source does not contain the expected file list.")
            if _read_exact(stream, list_name_size) != FILE_LIST_NAME:
                raise ExaFormatError("The EXA source does not contain the expected file list.")
            _read_record_header(stream)
            members = _parse_file_list(
                _read_zlib_record(
                    stream,
                    output_limit=FILE_LIST_SIZE_LIMIT,
                    budget=record_budget,
                ),
                file_count,
            )
            if sum(member.declared_size for member in members) > AGGREGATE_MEMBER_SIZE_LIMIT:
                raise ExaFormatError("The EXA source exceeds the aggregate member-size limit.")

            for listed_member in members:
                if _read_uint32(stream) != 0:
                    raise ExaFormatError("The EXA member framing is unsupported.")
                path_size = _read_uint32(stream)
                if path_size == 0 or path_size > PATH_LIMIT:
                    raise ExaFormatError("The EXA member path length is invalid.")
                record_path = _read_exact(stream, path_size)
                if record_path != listed_member.path_bytes:
                    raise ExaFormatError("The EXA member path does not match its file-list entry.")
                _read_record_header(stream)

                is_frm1 = _member_basename(record_path).casefold() == "frm1.edb"
                if is_frm1:
                    candidate_count += 1
                    if candidate_count > 1:
                        raise ExaFormatError("The EXA source contains multiple Frm1.edb members.")
                    descriptor = os.open(
                        target_path,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                        0o600,
                    )
                    target_created = True
                    try:
                        output: BinaryIO | None = os.fdopen(descriptor, "wb")
                    except BaseException as error:
                        try:
                            os.close(descriptor)
                        except OSError as cleanup_error:
                            error.add_note(
                                "The recovered-database descriptor could not be closed: "
                                f"{type(cleanup_error).__name__}."
                            )
                        raise
                else:
                    output = None

                recovered_size = 0
                try:
                    while recovered_size < listed_member.declared_size:
                        chunk = _read_zlib_record(
                            stream,
                            output_limit=min(
                                DECOMPRESSED_CHUNK_LIMIT,
                                listed_member.declared_size - recovered_size,
                            ),
                            budget=record_budget,
                        )
                        if not chunk:
                            raise ExaFormatError("The EXA source contains an empty member chunk.")
                        recovered_size += len(chunk)
                        if recovered_size > listed_member.declared_size:
                            raise ExaFormatError(
                                "An EXA member exceeds its declared decompressed size."
                            )
                        if output is not None:
                            output.write(chunk)
                finally:
                    if output is not None:
                        output.close()
                if recovered_size != listed_member.declared_size:
                    raise ExaFormatError("An EXA member does not match its declared size.")

            if _read_exact(stream, len(FOOTER)) != FOOTER or stream.read(1):
                raise ExaFormatError("The EXA source contains unexpected trailing data.")
    except ExaFormatError as error:
        if target_created:
            _remove_recovered_target(target_path, error)
        raise
    except OSError as error:
        source_error = ExaFormatError("The EXA source could not be read safely.")
        if target_created:
            _remove_recovered_target(target_path, source_error)
        raise source_error from error

    if candidate_count != 1 or not target_path.is_file():
        raise ExaFormatError("The EXA source does not contain exactly one Frm1.edb member.")
    with target_path.open("rb") as stream:
        sqlite_magic = stream.read(16)
    if sqlite_magic != b"SQLite format 3\x00":
        error = ExaFormatError("The recovered Frm1.edb is not a SQLite 3 database.")
        _remove_recovered_target(target_path, error)
        raise error
    return target_path
