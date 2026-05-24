# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ghrah namespace package.

ghrah-core: Ghrah 平台核心库

This file uses pkgutil-style namespace packages to allow multiple
packages to share the 'ghrah' namespace.
"""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

__version__ = "0.1.1"
