"""Private S3 quarantine. Finalized means inspected, never extracted/redacted for a model."""

import hashlib
from uuid import UUID, uuid4

import boto3
from botocore.config import Config

from billshield.db import AuthorizationError, TenantSession
from billshield.ports import UploadLink

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
CONTENT_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})


class InvalidUpload(ValueError):
    pass


def signature_type(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise InvalidUpload("Unsupported file signature")


class S3ObjectStorage:
    def __init__(
        self,
        endpoint: str,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str = "billshield-uploads",
        ttl: int = 120,
        client=None,
    ):
        if not 30 <= ttl <= 300:
            raise ValueError("Upload TTL must be between 30 and 300 seconds")
        self.bucket, self.ttl = bucket, ttl
        self.s3 = client or boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def create_upload(self, scope: TenantSession, size: int, content_type: str) -> UploadLink:
        if not 0 < size <= MAX_UPLOAD_BYTES or content_type not in CONTENT_TYPES:
            raise InvalidUpload("Upload must be PDF/PNG/JPEG and at most 10 MiB")
        file_id = uuid4()
        key = f"quarantine/{scope.org_id}/{file_id}/{uuid4()}"
        scope.connection.execute(
            "INSERT INTO billshield.files "
            "(id,org_id,uploaded_by,object_key,declared_size,declared_type,status) "
            "VALUES (%s,%s,%s,%s,%s,%s,'pending')",
            (file_id, scope.org_id, scope.user_id, key, size, content_type),
        )
        url = self.s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size,
            },
            ExpiresIn=self.ttl,
        )
        return UploadLink(
            file_id, url, {"Content-Type": content_type, "Content-Length": str(size)}, self.ttl
        )

    def _file(self, scope: TenantSession, file_id: UUID, *, lock: bool = False):
        # Explicit tenant qualification supplements (and never replaces) runtime RLS.
        row = scope.connection.execute(
            "SELECT * FROM billshield.files WHERE id=%s AND org_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (file_id, scope.org_id),
        ).fetchone()
        if not row:
            raise AuthorizationError("File unavailable")
        return row

    def finalize(self, scope: TenantSession, file_id: UUID) -> str:
        row = self._file(scope, file_id, lock=True)
        if row["uploaded_by"] != scope.user_id:
            raise AuthorizationError("Only the uploader can finalize this file")
        if row["status"] != "pending":
            raise InvalidUpload("File is not awaiting finalization")
        response = self.s3.get_object(Bucket=self.bucket, Key=row["object_key"])
        body = response["Body"]
        try:
            # Do not trust ContentLength or user-provided metadata to bound memory.
            data = body.read(MAX_UPLOAD_BYTES + 1)
        finally:
            body.close()
        try:
            detected = signature_type(data)
            if not 0 < len(data) <= MAX_UPLOAD_BYTES or len(data) != row["declared_size"]:
                raise InvalidUpload("Actual upload size differs from declaration or exceeds limit")
            if detected != row["declared_type"] or response.get("ContentType") != detected:
                raise InvalidUpload("Actual upload type differs from declaration")
        except InvalidUpload:
            scope.connection.execute(
                "UPDATE billshield.files SET status='rejected' WHERE id=%s AND org_id=%s",
                (file_id, scope.org_id),
            )
            raise
        digest = hashlib.sha256(data).hexdigest()
        # Freeze exactly the bytes inspected. The original PUT URL may still be live;
        # it cannot replace this new private object because its random key is never signed for PUT.
        frozen_key = f"quarantine/inspected/{scope.org_id}/{file_id}/{uuid4()}"
        self.s3.put_object(Bucket=self.bucket, Key=frozen_key, Body=data, ContentType=detected)
        scope.connection.execute(
            "UPDATE billshield.files SET status='ready',object_key=%s,actual_size=%s,"
            "actual_type=%s,sha256=%s WHERE id=%s AND org_id=%s",
            (frozen_key, len(data), detected, digest, file_id, scope.org_id),
        )
        return digest

    def download_link(self, scope: TenantSession, file_id: UUID) -> str:
        row = self._file(scope, file_id)
        if row["status"] != "ready":
            raise InvalidUpload("File has not passed upload inspection")
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": row["object_key"]},
            ExpiresIn=self.ttl,
        )
