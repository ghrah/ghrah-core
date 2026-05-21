# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


class ManifestError(Exception):
    pass


class ManifestValidationError(ManifestError):
    pass


class ManifestVersionError(ManifestError):
    pass


class ManifestNotFoundError(ManifestError):
    pass


class DuplicateManifestError(ManifestError):
    pass
