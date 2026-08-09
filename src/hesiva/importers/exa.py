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
MEMBER_SIZE_LIMIT = 16 * 1024 * 1024 * 1024
FILE_LIST_SIZE_LIMIT = FILE_COUNT_LIMIT * (PATH_LIMIT + 64)
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


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    if size < 0:
        raise ExaFormatError("The EXA source contains an invalid length.")
    value = stream.read(size)
    if len(value) != size:
        raise ExaFormatError("The EXA source is truncated.")
    return value


def _read_uint32(stream: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(stream, 4))[0]


def _read_zlib_record(stream: BinaryIO, *, output_limit: int) -> bytes:
    compressed_size = _read_uint32(stream)
    if compressed_size == 0 or compressed_size > COMPRESSED_CHUNK_LIMIT:
        raise ExaFormatError("The EXA source contains an unsupported compressed record.")
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
        declared_size = int(match.group(2))
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
                _read_zlib_record(stream, output_limit=FILE_LIST_SIZE_LIMIT),
                file_count,
            )

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
                    output: BinaryIO | None = os.fdopen(descriptor, "wb")
                else:
                    output = None

                recovered_size = 0
                try:
                    while recovered_size < listed_member.declared_size:
                        chunk = _read_zlib_record(
                            stream,
                            output_limit=listed_member.declared_size - recovered_size,
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
    except ExaFormatError:
        if target_created:
            target_path.unlink(missing_ok=True)
        raise
    except OSError as error:
        if target_created:
            target_path.unlink(missing_ok=True)
        raise ExaFormatError("The EXA source could not be read safely.") from error

    if candidate_count != 1 or not target_path.is_file():
        raise ExaFormatError("The EXA source does not contain exactly one Frm1.edb member.")
    with target_path.open("rb") as stream:
        sqlite_magic = stream.read(16)
    if sqlite_magic != b"SQLite format 3\x00":
        target_path.unlink()
        raise ExaFormatError("The recovered Frm1.edb is not a SQLite 3 database.")
    return target_path
