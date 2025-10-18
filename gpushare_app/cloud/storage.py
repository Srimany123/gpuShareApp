"""
Cloud storage integration
========================

This module provides helpers for uploading files to various cloud
storage back‑ends.  Supported providers include Nextcloud via WebDAV,
Google Cloud Storage (GCS) and any Amazon S3 compatible service
(e.g. AWS S3 or Cloudflare R2).  A generic ``upload_file`` function
selects the appropriate helper based on the ``STORAGE_PROVIDER``
configuration option.  If cloud storage is not configured the helper
will simply write files to a local ``uploads/`` directory.

Environment/Configuration
-------------------------

In addition to the Nextcloud settings documented in
``gpushare_app.config``, the following environment variables may be
used:

``STORAGE_PROVIDER``
    Name of the storage provider.  One of ``local`` (default),
    ``nextcloud``, ``gcs``, ``s3`` or ``r2``.  ``r2`` is treated the
    same as ``s3`` but allows specifying a custom endpoint.

``STORAGE_BUCKET``
    Name of the bucket or container used by GCS/S3 providers.

``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``
    Credentials for S3/R2 providers.  These must be set when using
    ``s3`` or ``r2``.

``AWS_ENDPOINT_URL``
    Optional custom endpoint URL for S3 compatible providers (e.g.
    ``https://<account_id>.r2.cloudflarestorage.com`` for Cloudflare R2).

``GCS_CREDENTIALS_JSON``
    Path to a Google Cloud service account JSON file.  If omitted the
    default credentials chain is used (see the Google Cloud Python
    documentation).

``NEXTCLOUD_URL``, ``NEXTCLOUD_USERNAME``, ``NEXTCLOUD_PASSWORD``
    Credentials for Nextcloud (as described in ``config.py``).

These variables should be defined in your ``.env`` file to enable
cloud storage.  See the README for more details.
"""

from __future__ import annotations

import os
from typing import Optional

import requests  # type: ignore
from flask import current_app


def upload_to_nextcloud(file_bytes: bytes, filename: str) -> str:
    """Upload a file to Nextcloud via WebDAV.

    The Nextcloud credentials are read from the application
    configuration (``NEXTCLOUD_URL``, ``NEXTCLOUD_USERNAME``,
    ``NEXTCLOUD_PASSWORD``).  If any of these are missing this
    function will raise a ``RuntimeError``.

    Parameters
    ----------
    file_bytes: bytes
        The file contents to upload.
    filename: str
        The destination filename (relative to the root of the WebDAV
        directory).

    Returns
    -------
    str
        The URL of the uploaded file.
    """
    cfg = current_app.config
    nc_url: Optional[str] = cfg.get("NEXTCLOUD_URL")
    nc_user: Optional[str] = cfg.get("NEXTCLOUD_USERNAME")
    nc_pass: Optional[str] = cfg.get("NEXTCLOUD_PASSWORD")
    if not (nc_url and nc_user and nc_pass):
        raise RuntimeError("Nextcloud configuration missing")
    upload_url = nc_url.rstrip("/") + "/" + filename
    resp = requests.put(upload_url, data=file_bytes, auth=(nc_user, nc_pass))
    resp.raise_for_status()
    return upload_url


def upload_to_gcs(file_bytes: bytes, filename: str) -> str:
    """Upload a file to Google Cloud Storage.

    Requires the ``google-cloud-storage`` package.  Credentials are
    obtained from the ``GCS_CREDENTIALS_JSON`` environment variable or
    via the default credentials chain.  The destination bucket name
    must be provided via ``STORAGE_BUCKET`` (or ``GCS_BUCKET``) in the
    environment or application config.

    Returns the ``gs://`` URI of the uploaded object.
    """
    try:
        from google.cloud import storage as gcs_storage  # type: ignore
    except Exception as exc:
        raise RuntimeError("google-cloud-storage is not installed") from exc
    cfg = current_app.config
    bucket_name: Optional[str] = cfg.get("STORAGE_BUCKET") or cfg.get("GCS_BUCKET")
    if not bucket_name:
        raise RuntimeError("GCS bucket name not configured (STORAGE_BUCKET/GCS_BUCKET)")
    cred_path = os.environ.get("GCS_CREDENTIALS_JSON")
    if cred_path:
        client = gcs_storage.Client.from_service_account_json(cred_path)
    else:
        client = gcs_storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_string(file_bytes)
    return f"gs://{bucket_name}/{filename}"


def upload_to_s3(file_bytes: bytes, filename: str) -> str:
    """Upload a file to an S3 compatible service (AWS S3, R2).

    This helper uses ``boto3``.  It reads credentials from the
    standard AWS environment variables ``AWS_ACCESS_KEY_ID`` and
    ``AWS_SECRET_ACCESS_KEY``.  For R2 or other custom endpoints you
    can set ``AWS_ENDPOINT_URL``.  The destination bucket name must
    be specified via ``STORAGE_BUCKET``.

    Returns the ``s3://`` style URI of the uploaded object.
    """
    try:
        import boto3  # type: ignore
    except Exception as exc:
        raise RuntimeError("boto3 is not installed") from exc
    cfg = current_app.config
    bucket_name: Optional[str] = cfg.get("STORAGE_BUCKET") or cfg.get("S3_BUCKET")
    if not bucket_name:
        raise RuntimeError("S3 bucket name not configured (STORAGE_BUCKET/S3_BUCKET)")
    aws_endpoint = os.environ.get("AWS_ENDPOINT_URL")
    s3 = boto3.client("s3", endpoint_url=aws_endpoint)
    s3.put_object(Bucket=bucket_name, Key=filename, Body=file_bytes)
    return f"s3://{bucket_name}/{filename}"


def upload_to_local(file_bytes: bytes, filename: str) -> str:
    """Save a file to the local filesystem under ``uploads/``.

    Creates the uploads directory if it does not exist.  Returns the
    absolute path to the stored file.
    """
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, filename)
    with open(path, "wb") as f:
        f.write(file_bytes)
    return path


def upload_file(file_bytes: bytes, filename: str) -> str:
    """Generalised file upload helper.

    This function inspects the ``STORAGE_PROVIDER`` configuration
    option to determine which backend to use.  Supported providers:

      * ``nextcloud`` – use WebDAV to a Nextcloud instance via
        :func:`upload_to_nextcloud`.
      * ``gcs`` – upload to Google Cloud Storage via
        :func:`upload_to_gcs`.
      * ``s3`` or ``r2`` – upload to an S3 compatible service via
        :func:`upload_to_s3`.
      * ``local`` (default) – save to the local filesystem via
        :func:`upload_to_local`.

    If the chosen provider is misconfigured or a required package is
    missing, a ``RuntimeError`` will be raised.
    """
    provider = (current_app.config.get("STORAGE_PROVIDER") or os.environ.get("STORAGE_PROVIDER") or "local").lower()
    if provider == "nextcloud":
        return upload_to_nextcloud(file_bytes, filename)
    if provider == "gcs":
        return upload_to_gcs(file_bytes, filename)
    if provider in {"s3", "r2"}:
        return upload_to_s3(file_bytes, filename)
    # Default to local storage
    return upload_to_local(file_bytes, filename)