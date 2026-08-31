# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""集群通信 Ability 共享常量。"""

_NO_SUPERVISOR_ERROR = (
    "No supervisor configured. "
    "Cluster abilities require a SupervisorActor to be injected "
    "via AbilityExecutionContext.supervisor."
)
