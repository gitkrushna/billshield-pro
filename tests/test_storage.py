from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from billshield.db import AuthorizationError, TenantSession
from billshield.storage import MAX_UPLOAD_BYTES, InvalidUpload, S3ObjectStorage


@pytest.fixture
def setup():
    org, user, file_id = uuid4(), uuid4(), uuid4()
    row = {
        "id": file_id,
        "org_id": org,
        "uploaded_by": user,
        "object_key": "quarantine/original",
        "declared_size": 12,
        "declared_type": "application/pdf",
        "status": "pending",
    }
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = row
    scope = TenantSession(connection, user, org, "member")
    s3 = Mock()
    storage = S3ObjectStorage(
        "http://localhost:9000", "fixture", "fixture", "fixture", client=s3
    )
    return SimpleNamespace(
        row=row, scope=scope, s3=s3, storage=storage, file_id=file_id
    )


def test_file_authorization_happens_before_storage_access(setup):
    setup.scope.connection.execute.return_value.fetchone.return_value = None
    with pytest.raises(AuthorizationError):
        setup.storage.download_link(setup.scope, setup.file_id)
    assert not setup.s3.mock_calls


def test_another_member_cannot_finalize_users_upload(setup):
    setup.row["uploaded_by"] = uuid4()
    with pytest.raises(AuthorizationError):
        setup.storage.finalize(setup.scope, setup.file_id)
    assert not setup.s3.mock_calls


def test_inspected_bytes_are_frozen_separately_from_original_put_key(setup):
    data = b"%PDF-fixture"
    setup.s3.get_object.return_value = {
        "Body": BytesIO(data),
        "ContentType": "application/pdf",
    }
    digest = setup.storage.finalize(setup.scope, setup.file_id)
    assert len(digest) == 64
    frozen = setup.s3.put_object.call_args.kwargs
    assert frozen["Key"] != setup.row["object_key"]
    assert frozen["Key"].startswith("quarantine/inspected/")
    assert frozen["Body"] == data
    assert "ACL" not in frozen


@pytest.mark.parametrize(
    "data,content_type",
    [
        (b"not a PDF!!!", "application/pdf"),
        (b"%PDF-fixture-extra", "application/pdf"),
        (b"%PDF-fixture", "image/png"),
        (b"%PDF-" + b"x" * MAX_UPLOAD_BYTES, "application/pdf"),
    ],
    ids=["bad-signature", "size-mismatch", "type-mismatch", "oversize"],
)
def test_actual_bytes_and_type_must_match_declaration(setup, data, content_type):
    setup.s3.get_object.return_value = {
        "Body": BytesIO(data),
        "ContentType": content_type,
    }
    with pytest.raises(InvalidUpload):
        setup.storage.finalize(setup.scope, setup.file_id)
    setup.s3.put_object.assert_not_called()


def test_presigned_put_has_short_ttl_and_signed_size_type(setup):
    setup.s3.generate_presigned_url.return_value = "https://fixture.invalid/signed"
    result = setup.storage.create_upload(setup.scope, 42, "image/png")
    params = setup.s3.generate_presigned_url.call_args.kwargs
    assert params["Params"]["ContentLength"] == 42
    assert params["Params"]["ContentType"] == "image/png"
    assert result.expires_in <= 300
    assert result.headers == {"Content-Type": "image/png", "Content-Length": "42"}
