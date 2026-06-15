# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""向后兼容模块：所有符号已迁移至 ghrah.abilities.paths 公共模块。

新代码请使用 ``from ghrah.abilities.paths import ...`` 或 ``from ghrah.abilities import ...``。
"""

from ghrah.abilities.paths import (
    ABILITY_PATH_SPECS,
    AbilityPathSpec,
    extract_paths,
    is_subpath,
)

__all__ = ["is_subpath", "AbilityPathSpec", "ABILITY_PATH_SPECS", "extract_paths"]
