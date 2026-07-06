<script setup lang="ts">
import { computed } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import StatCard from '@/components/dashboard/StatCard.vue'
import HealthScoreRing from '@/components/dashboard/HealthScoreRing.vue'
import ServerHealthIndicator from '@/components/dashboard/ServerHealthIndicator.vue'
import ServiceStatusCard from '@/components/dashboard/ServiceStatusCard.vue'
import ApplicationStatusCard from '@/components/dashboard/ApplicationStatusCard.vue'
import AlertList from '@/components/dashboard/AlertList.vue'
import ResourceChart from '@/components/dashboard/ResourceChart.vue'
import ActivityTimeline from '@/components/dashboard/ActivityTimeline.vue'
import DeploymentList from '@/components/dashboard/DeploymentList.vue'
import QuickActions from '@/components/dashboard/QuickActions.vue'
import { useDashboard } from '@/composables/useDashboard'
import { IconServer } from '@/components/icons'

const { data, loading, refreshing, error, runningServices, activeApplications, refresh } =
  useDashboard()

const primaryStats = computed(() => data.value?.stats.slice(0, 4) ?? [])
const secondaryStats = computed(() => data.value?.stats.slice(4) ?? [])
</script>

<template>
  <DashboardLayout :refreshing="refreshing" @refresh="refresh">
    <ErrorState v-if="error && !data" :message="error" @retry="refresh" />

    <div v-else class="animate-fade-in space-y-5 md:space-y-6">
      <!-- Hero row: health score + primary stats -->
      <section class="dashboard-grid lg:grid-cols-12" aria-label="Platform overview">
        <div class="animate-slide-up lg:col-span-3">
          <HealthScoreRing
            :score="data?.healthScore ?? 0"
            :status="data?.readiness?.status || data?.health?.status || 'degraded'"
            :environment="data?.health?.environment"
            :version="data?.health?.version"
            :loading="loading"
          />
        </div>

        <div class="dashboard-grid sm:grid-cols-2 lg:col-span-9 xl:grid-cols-4">
          <StatCard
            v-for="stat in primaryStats"
            :key="stat.id"
            :stat="stat"
            :loading="loading"
            class="animate-slide-up"
          />
        </div>
      </section>

      <!-- Secondary stats -->
      <section
        class="dashboard-grid grid-cols-2 md:grid-cols-4"
        aria-label="Infrastructure metrics"
      >
        <StatCard
          v-for="stat in secondaryStats"
          :key="stat.id"
          :stat="stat"
          :loading="loading"
        />
      </section>

      <!-- VPS inventory -->
      <section
        v-if="data?.inventory"
        class="dashboard-grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7"
        aria-label="VPS inventory"
      >
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Registered apps</p>
          <p class="text-xl font-semibold">{{ data.inventory.registered_apps }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Discovered apps</p>
          <p class="text-xl font-semibold text-sky-600">{{ data.inventory.discovered_apps }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Unregistered</p>
          <p class="text-xl font-semibold text-amber-600">{{ data.inventory.unregistered_discovered_apps }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Domain drift</p>
          <p class="text-xl font-semibold text-amber-600">{{ data.inventory.domains_with_drift }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Certs expiring</p>
          <p class="text-xl font-semibold text-amber-600">{{ data.inventory.certificates_expiring }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Certs missing</p>
          <p class="text-xl font-semibold text-red-600">{{ data.inventory.certificates_missing }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Runtime issues</p>
          <p class="text-xl font-semibold">{{ data.inventory.runtime_issues }}</p>
        </Card>
      </section>

      <section aria-label="Quick actions">
        <Card title="Quick Actions" padding="sm" class="min-w-0 overflow-hidden">
          <QuickActions :refreshing="refreshing" @refresh="refresh" />
        </Card>
      </section>

      <!-- Charts -->
      <section class="dashboard-grid lg:grid-cols-3" aria-label="Resource utilization charts">
        <Card title="CPU Usage" subtitle="Live · updates every 5s" class="animate-slide-up">
          <ResourceChart
            title="CPU"
            :chart="data?.charts.cpu ?? { categories: [], series: [] }"
            :loading="loading"
            unit="%"
          />
        </Card>
        <Card title="Memory Usage" subtitle="Live · updates every 5s" class="animate-slide-up">
          <ResourceChart
            title="Memory"
            :chart="data?.charts.memory ?? { categories: [], series: [] }"
            :loading="loading"
            unit="%"
          />
        </Card>
        <Card title="Network Throughput" subtitle="Live · updates every 5s" class="animate-slide-up">
          <template #actions>
            <div class="text-right text-xs text-surface-muted">
              <p>↓ {{ data?.networkThroughput.in }}</p>
              <p>↑ {{ data?.networkThroughput.out }}</p>
            </div>
          </template>
          <ResourceChart
            title="Network"
            :chart="data?.charts.network ?? { categories: [], series: [] }"
            :loading="loading"
            unit=""
          />
        </Card>
      </section>

      <!-- Servers + Services -->
      <section class="dashboard-grid items-start xl:grid-cols-2" aria-label="Servers and services">
        <Card
          title="Server Health"
          :subtitle="`${data?.servers.length ?? 0} nodes monitored`"
          class="min-w-0"
        >
          <div v-if="!data?.servers.length && !loading" class="dashboard-side-panel py-4 text-sm text-surface-muted">
            No server metrics available yet.
          </div>
          <div v-else class="dashboard-side-panel">
            <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              <ServerHealthIndicator
                v-for="server in data?.servers ?? []"
                :key="server.id"
                :server="server"
              />
            </div>
          </div>
        </Card>

        <Card
          title="Running Services"
          :subtitle="`${runningServices} of ${data?.services.length ?? 0} active`"
          class="min-w-0"
        >
          <div class="dashboard-side-panel">
            <div class="dashboard-side-panel-scroll space-y-2">
              <ServiceStatusCard
                v-for="service in data?.services ?? []"
                :key="service.id"
                :service="service"
              >
                <template #icon>
                  <IconServer :size="16" class="text-brand-500" />
                </template>
              </ServiceStatusCard>
            </div>
          </div>
        </Card>
      </section>

      <!-- Applications + Alerts -->
      <section class="dashboard-grid xl:grid-cols-5" aria-label="Applications and alerts">
        <Card
          class="xl:col-span-2"
          title="Active Applications"
          :subtitle="`${activeApplications} running`"
        >
          <div class="grid gap-2 sm:grid-cols-2">
            <ApplicationStatusCard
              v-for="app in data?.applications ?? []"
              :key="app.id"
              :application="app"
            />
          </div>
        </Card>

        <Card class="xl:col-span-3" title="Recent Alerts" subtitle="Last 24 hours">
          <AlertList :alerts="data?.alerts ?? []" :loading="loading" :max-items="5" />
        </Card>
      </section>

      <!-- Deployments + Activity -->
      <section class="dashboard-grid min-w-0 xl:grid-cols-2" aria-label="Deployments and activity">
        <Card title="Recent Deployments" class="min-w-0 overflow-hidden">
          <DeploymentList :deployments="data?.deployments ?? []" :loading="loading" />
        </Card>

        <Card title="Activity Timeline" class="min-w-0 overflow-hidden">
          <ActivityTimeline :items="data?.activities ?? []" :loading="loading" />
        </Card>
      </section>

      <!-- Load average footer -->
      <section
        class="flex flex-wrap items-center gap-4 rounded-xl border border-surface-border bg-surface-raised px-4 py-3 text-xs text-surface-muted"
        aria-label="Load average"
      >
        <span class="font-medium text-slate-700 dark:text-slate-200">Load average</span>
        <span v-for="(load, i) in data?.loadAverage ?? []" :key="i" class="tabular-nums">
          {{ ['1m', '5m', '15m'][i] }}: <strong class="text-slate-900 dark:text-white">{{ load }}</strong>
        </span>
      </section>
    </div>
  </DashboardLayout>
</template>
