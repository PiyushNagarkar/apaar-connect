import React, { useState } from 'react';
import {
  Layers,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Info,
  Shield,
  Eye,
  Database,
  Search,
  Filter,
  Download,
  Fingerprint,
  Building2,
  Scale,
  Users,
  Award,
  BookOpen,
} from 'lucide-react';
import { StatusChip } from '../../components/design-system/StatusChip';
import { LayerBadge } from '../../components/design-system/LayerBadge';
import { KpiCard } from '../../components/design-system/KpiCard';
import { DataTable } from '../../components/design-system/DataTable';
import { SeatBar } from '../../components/design-system/SeatBar';
import { EmptyState } from '../../components/design-system/EmptyState';
import { ErrorState } from '../../components/design-system/ErrorState';
import { NoPermissionState } from '../../components/design-system/NoPermissionState';
import {
  SkeletonCard,
  SkeletonTable,
  SkeletonText,
  SkeletonBadge,
} from '../../components/design-system/Skeleton';
import { ConfirmDialog } from '../../components/design-system/ConfirmDialog';
import { Timeline } from '../../components/design-system/Timeline';
import { MaskedValue } from '../../components/design-system/MaskedValue';
import { FooterBanner } from '../../components/design-system/FooterBanner';
import { TableColumn, TimelineEvent } from '../../types';

// Mock table dataset for showroom
interface DemoStudentRow {
  id: string;
  name: string;
  apaarMasked: string;
  category: string;
  quotaType: string;
  status: string;
  l1: string;
  l2: string;
  l3: string;
  score: number;
}

const MOCK_DATASET: DemoStudentRow[] = [
  {
    id: 'STU-1001',
    name: 'Aarav Sharma',
    apaarMasked: '987654321012',
    category: 'OPEN',
    quotaType: 'REGULAR',
    status: 'CONFIRMED',
    l1: 'PASS',
    l2: 'PASS',
    l3: 'PASS',
    score: 96.5,
  },
  {
    id: 'STU-1002',
    name: 'Priya Patel',
    apaarMasked: '234567890123',
    category: 'OBC',
    quotaType: 'REGULAR',
    status: 'CONFIRMED',
    l1: 'PASS',
    l2: 'PASS',
    l3: 'PASS',
    score: 92.0,
  },
  {
    id: 'STU-1003',
    name: 'Siddharth Rao',
    apaarMasked: '999900001111',
    category: 'OPEN',
    quotaType: 'REGULAR',
    status: 'PROVISIONAL',
    l1: 'UNAVAILABLE',
    l2: 'SKIPPED',
    l3: 'SKIPPED',
    score: 84.0,
  },
  {
    id: 'STU-1004',
    name: 'Sneha Kulkarni',
    apaarMasked: '456789012345',
    category: 'TFW',
    quotaType: 'SUPERNUMERARY',
    status: 'CONFIRMED',
    l1: 'PASS',
    l2: 'PASS',
    l3: 'PASS',
    score: 95.0,
  },
  {
    id: 'STU-1005',
    name: 'Vikram Singh',
    apaarMasked: '567890123456',
    category: 'OPEN',
    quotaType: 'REGULAR',
    status: 'UNDER_REVIEW',
    l1: 'PASS',
    l2: 'PASS',
    l3: 'FAIL',
    score: 68.5,
  },
  {
    id: 'STU-1006',
    name: 'Amit Jadhav',
    apaarMasked: '750000000014',
    category: 'OPEN',
    quotaType: 'REGULAR',
    status: 'UNDER_REVIEW',
    l1: 'PASS',
    l2: 'PASS',
    l3: 'FAIL',
    score: 55.0,
  },
];

const MOCK_TIMELINE: TimelineEvent[] = [
  {
    id: 'evt-1',
    title: 'Batch Enrollment Ingestion',
    timestamp: '2024-07-15 10:30 UTC',
    statusVariant: 'info',
    statusLabel: 'Submitted',
    actor: 'Vikas Patil',
    role: 'INSTITUTION_OPERATOR',
    description: 'Student admission record submitted for COEP B.Tech CSE (Batch 2024-2025).',
  },
  {
    id: 'evt-2',
    title: 'L1 Identity Check Completed',
    timestamp: '2024-07-15 10:31 UTC',
    statusVariant: 'verified',
    statusLabel: 'Passed (99%)',
    actor: 'APAAR Identity Adapter',
    role: 'SYSTEM',
    description: 'Demographic and checksum matched successfully with simulated central registry.',
  },
  {
    id: 'evt-3',
    title: 'L2 Authority & Intake Verification',
    timestamp: '2024-07-15 10:31 UTC',
    statusVariant: 'verified',
    statusLabel: 'Compliant',
    actor: 'AICTE Approval Engine',
    role: 'SYSTEM',
    description: 'Program valid under AICTE Approval Order #F.No. Western/1-11110001/2024.',
  },
  {
    id: 'evt-4',
    title: 'L3 Compliance & Duplicate Verification',
    timestamp: '2024-07-15 10:32 UTC',
    statusVariant: 'verified',
    statusLabel: 'Verified',
    actor: 'AICTE Anomaly Engine',
    role: 'SYSTEM',
    description: 'No cross-institutional duplicate APAAR matches found; quota strictly isolated.',
  },
  {
    id: 'evt-5',
    title: 'Verifiable Credential Issued',
    timestamp: '2024-07-16 09:15 UTC',
    statusVariant: 'verified',
    statusLabel: 'Active QR',
    actor: 'Dr. Anand Joshi',
    role: 'INSTITUTION_ADMIN',
    description: 'Ed25519 digital credential signed with key ID aicte-prod-2024-v1 and published.',
  },
];

export const ComponentShowcase: React.FC = () => {
  // Interactive test states
  const [tableLoading, setTableLoading] = useState(false);
  const [tableEmpty, setTableEmpty] = useState(false);
  const [tableError, setTableError] = useState(false);
  const [tableSearch, setTableSearch] = useState('');
  const [tablePage, setTablePage] = useState(1);
  const [tablePageSize, setTablePageSize] = useState(10);
  const [kpiLoading, setKpiLoading] = useState(false);
  const [kpiActive, setKpiActive] = useState('total');
  const [selectedStudent, setSelectedStudent] = useState<string | null>(null);

  // Confirm dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogResult, setDialogResult] = useState<string | null>(null);

  // Filtered demo data
  const filteredData = tableEmpty
    ? []
    : MOCK_DATASET.filter((item) => {
        if (!tableSearch) return true;
        const q = tableSearch.toLowerCase();
        return (
          item.name.toLowerCase().includes(q) ||
          item.id.toLowerCase().includes(q) ||
          item.category.toLowerCase().includes(q) ||
          item.status.toLowerCase().includes(q)
        );
      });

  const tableColumns: TableColumn<DemoStudentRow>[] = [
    {
      key: 'id',
      header: 'Student ID',
      width: '120px',
      accessor: (r) => <span className="font-mono text-xs font-semibold">{r.id}</span>,
    },
    {
      key: 'name',
      header: 'Student Name',
      sortable: true,
      accessor: (r) => <span className="font-bold text-slate-900">{r.name}</span>,
    },
    {
      key: 'apaarMasked',
      header: 'APAAR ID (Masked)',
      accessor: (r) => <MaskedValue value={r.apaarMasked} type="apaar" />,
    },
    {
      key: 'category',
      header: 'Category / Quota',
      accessor: (r) => (
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-slate-800">{r.category}</span>
          <span className="text-[10px] text-slate-500 font-mono">({r.quotaType})</span>
        </div>
      ),
    },
    {
      key: 'verification',
      header: '3-Layer Verification',
      accessor: (r) => <LayerBadge l1={r.l1} l2={r.l2} l3={r.l3} mode="compact" />,
    },
    {
      key: 'status',
      header: 'Admission Status',
      sortable: true,
      accessor: (r) => <StatusChip status={r.status} size="sm" />,
    },
  ];

  return (
    <div className="space-y-12 pb-16">
      {/* Showroom Header */}
      <div className="bg-gradient-to-r from-[#0a192f] via-blue-950 to-slate-900 text-white rounded-xl p-6 sm:p-8 shadow-lg border border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-2.5 py-0.5 rounded bg-blue-500/20 text-blue-300 font-bold uppercase text-[11px] tracking-wider border border-blue-500/30">
                Design System v2.0
              </span>
              <span className="text-slate-400 text-xs">WCAG AA Compliant • Mobile-First</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
              Component & Design System Showroom
            </h1>
            <p className="text-xs sm:text-sm text-slate-300 mt-1 max-w-2xl leading-relaxed">
              Living design specification for AICTE APAAR Connect. Demonstrates every atomic and
              composite component across all states (default, loading, empty, error, no permission).
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                setTableLoading(false);
                setTableEmpty(false);
                setTableError(false);
                setKpiLoading(false);
                setDialogResult(null);
              }}
              className="px-3 py-1.5 rounded-lg bg-blue-800 hover:bg-blue-700 text-white text-xs font-semibold shadow-xs transition-colors"
            >
              Reset All States
            </button>
          </div>
        </div>
      </div>

      {/* ---------------- 1. Color Palette & Typography Tokens ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-900" />
            1. Core Government-Tech Color System & Semantics
          </h2>
          <p className="text-xs text-slate-500">
            Calm, authoritative government palette: Deep Navy primary, clean surfaces, and unambiguous status tokens with mandatory icons.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div className="bg-white p-3.5 rounded-lg border border-slate-200 shadow-2xs">
            <div className="w-full h-10 rounded bg-[#0a192f] mb-2 flex items-center justify-center text-white text-xs font-mono font-bold">
              #0a192f
            </div>
            <p className="text-xs font-bold text-slate-900">Deep Navy Primary</p>
            <p className="text-[11px] text-slate-500">Header, Sidebar, Apex Authority</p>
          </div>

          <div className="bg-white p-3.5 rounded-lg border border-slate-200 shadow-2xs">
            <div className="w-full h-10 rounded bg-emerald-600 mb-2 flex items-center justify-center text-white text-xs font-mono font-bold">
              #059669
            </div>
            <p className="text-xs font-bold text-slate-900">Green (Verified)</p>
            <p className="text-[11px] text-slate-500">Confirmed, Compliant, Pass</p>
          </div>

          <div className="bg-white p-3.5 rounded-lg border border-slate-200 shadow-2xs">
            <div className="w-full h-10 rounded bg-amber-500 mb-2 flex items-center justify-center text-white text-xs font-mono font-bold">
              #d97706
            </div>
            <p className="text-xs font-bold text-slate-900">Amber (Under Review)</p>
            <p className="text-[11px] text-slate-500">Pending, At Limit, Warning</p>
          </div>

          <div className="bg-white p-3.5 rounded-lg border border-slate-200 shadow-2xs">
            <div className="w-full h-10 rounded bg-rose-600 mb-2 flex items-center justify-center text-white text-xs font-mono font-bold">
              #dc2626
            </div>
            <p className="text-xs font-bold text-slate-900">Red (Critical / Breach)</p>
            <p className="text-[11px] text-slate-500">Exceeded, Rejected, Revoked</p>
          </div>

          <div className="bg-white p-3.5 rounded-lg border border-slate-200 shadow-2xs">
            <div className="w-full h-10 rounded bg-slate-400 mb-2 flex items-center justify-center text-white text-xs font-mono font-bold">
              #64748b
            </div>
            <p className="text-xs font-bold text-slate-900">Grey (Unavailable)</p>
            <p className="text-[11px] text-slate-500">Service Outage, Skipped, Not Checked</p>
          </div>
        </div>
      </section>

      {/* ---------------- 2. StatusChip Component ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-600" />
            2. StatusChip (WCAG AA Compliant — Never Color Alone)
          </h2>
          <p className="text-xs text-slate-500">
            Always renders both high-contrast text and a semantic icon. Fully supports sm, md, and lg sizes.
          </p>
        </div>

        <div className="bg-white p-5 rounded-lg border border-slate-200 space-y-4 shadow-2xs">
          <div>
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Status Palette Mapping
            </h3>
            <div className="flex flex-wrap items-center gap-3">
              <StatusChip status="CONFIRMED" label="Verified / Confirmed" />
              <StatusChip status="UNDER_REVIEW" label="Under Review / Pending" />
              <StatusChip status="CRITICAL" label="Critical Breach / Exceeded" />
              <StatusChip status="UNAVAILABLE" label="Service Unavailable" />
              <StatusChip status="PROVISIONAL" label="Provisional / Submitted" />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Chip Sizes (sm, md, lg)
            </h3>
            <div className="flex flex-wrap items-center gap-3">
              <StatusChip status="CONFIRMED" size="sm" label="Small Pill (sm)" />
              <StatusChip status="CONFIRMED" size="md" label="Medium Standard (md)" />
              <StatusChip status="CONFIRMED" size="lg" label="Large Primary (lg)" />
            </div>
          </div>
        </div>
      </section>

      {/* ---------------- 3. LayerBadge (3-Layer Architecture) ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-700" />
            3. LayerBadge (Identity / Authority / Compliance)
          </h2>
          <p className="text-xs text-slate-500">
            Visualizes L1 Identity, L2 Statutory Program Authority, and L3 Quota & De-duplication.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Compact View Showcase */}
          <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-2xs space-y-3">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Compact Table Cell Mode
            </h3>
            <div className="space-y-3">
              <div>
                <p className="text-xs text-slate-500 mb-1 font-semibold">100% Fully Compliant:</p>
                <LayerBadge l1="PASS" l2="PASS" l3="PASS" mode="compact" />
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1 font-semibold">L1 Unavailable (Triggers Provisional):</p>
                <LayerBadge l1="UNAVAILABLE" l2="SKIPPED" l3="SKIPPED" mode="compact" />
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1 font-semibold">L3 Capacity Exceeded / Anomaly:</p>
                <LayerBadge l1="PASS" l2="PASS" l3="FAIL" mode="compact" />
              </div>
            </div>
          </div>

          {/* Expanded Interactive Inspector */}
          <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-2xs">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Expanded Inspector Mode
            </h3>
            <LayerBadge
              l1={{ status: 'PASS', reason: 'Demographic matched (98.4%)' }}
              l2={{ status: 'PASS', reason: 'Order #F.No.1-11110001 active' }}
              l3={{ status: 'FAIL', reason: 'Duplicate candidate detected: Cross-institution' }}
              mode="expanded"
            />
          </div>
        </div>
      </section>

      {/* ---------------- 4. KpiCard Component ---------------- */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
          <div>
            <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-700" />
              4. KpiCard (Clickable Drill-Down & Trend Indicators)
            </h2>
            <p className="text-xs text-slate-500">
              Clickable metric tiles that filter underlying tables and show status accents.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setKpiLoading(!kpiLoading)}
            className="px-2.5 py-1 text-xs font-medium rounded border border-slate-300 bg-white hover:bg-slate-50 text-slate-700"
          >
            {kpiLoading ? 'Show Normal Cards' : 'Simulate Skeleton Pulse'}
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard
            title="Total Approved Intake"
            value="1,450"
            subtitle="Across 3 frozen program matrixes"
            trend={{ direction: 'neutral', label: 'Fixed ceiling' }}
            icon={Building2}
            accentColor="primary"
            active={kpiActive === 'total'}
            isLoading={kpiLoading}
            onClick={() => setKpiActive('total')}
          />

          <KpiCard
            title="Confirmed Students"
            value="1,382"
            subtitle="95.3% national seat utilization"
            trend={{ direction: 'up', percentage: 4.2, label: 'vs last round' }}
            icon={CheckCircle2}
            accentColor="success"
            active={kpiActive === 'confirmed'}
            isLoading={kpiLoading}
            onClick={() => setKpiActive('confirmed')}
          />

          <KpiCard
            title="Open Review Cases"
            value="14"
            subtitle="High & critical discrepancy queue"
            trend={{ direction: 'down', percentage: 12.5, label: 'reduced' }}
            icon={AlertTriangle}
            accentColor="warning"
            badge={{ text: 'Action Req', variant: 'review' }}
            active={kpiActive === 'reviews'}
            isLoading={kpiLoading}
            onClick={() => setKpiActive('reviews')}
          />

          <KpiCard
            title="Capacity Breaches"
            value="2"
            subtitle="Rule 3 intake overflows detected"
            icon={XCircle}
            accentColor="danger"
            badge={{ text: 'Critical', variant: 'critical' }}
            active={kpiActive === 'breaches'}
            isLoading={kpiLoading}
            onClick={() => setKpiActive('breaches')}
          />
        </div>
      </section>

      {/* ---------------- 5. SeatBar (Capacity & Quota Isolation) ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-indigo-700" />
            5. SeatBar (Category-Isolated Seat Matrices)
          </h2>
          <p className="text-xs text-slate-500">
            Guarantees Rule 3 compliance: Supernumerary allocations are strictly isolated and never displace regular intake.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <SeatBar
            category="REGULAR - OPEN"
            quotaType="REGULAR"
            approved={60}
            occupied={48}
            provisional={4}
          />

          <SeatBar
            category="REGULAR - OBC"
            quotaType="REGULAR"
            approved={30}
            occupied={30}
            provisional={0}
          />

          <SeatBar
            category="REGULAR - OVERFLOW BREACH"
            quotaType="REGULAR"
            approved={30}
            occupied={35}
            provisional={0}
          />

          <SeatBar
            category="SUPERNUMERARY - TFW (Tuition Fee Waiver)"
            quotaType="SUPERNUMERARY"
            approved={3}
            occupied={3}
            provisional={0}
          />
        </div>
      </section>

      {/* ---------------- 6. DataTable Component ---------------- */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-2">
          <div>
            <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-900" />
              6. DataTable (Server-Side Pagination, Filtering & Sticky Header)
            </h2>
            <p className="text-xs text-slate-500">
              Interactive high-performance table with loading, empty, and error state simulators.
            </p>
          </div>

          {/* Interactive State Toggles */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => {
                setTableLoading(!tableLoading);
                setTableEmpty(false);
                setTableError(false);
              }}
              className={`px-3 py-1.5 rounded font-medium border transition-colors ${
                tableLoading
                  ? 'bg-blue-900 text-white border-blue-900'
                  : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
              }`}
            >
              Loading Skeleton
            </button>

            <button
              type="button"
              onClick={() => {
                setTableEmpty(!tableEmpty);
                setTableLoading(false);
                setTableError(false);
              }}
              className={`px-3 py-1.5 rounded font-medium border transition-colors ${
                tableEmpty
                  ? 'bg-blue-900 text-white border-blue-900'
                  : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
              }`}
            >
              Empty State
            </button>

            <button
              type="button"
              onClick={() => {
                setTableError(!tableError);
                setTableLoading(false);
                setTableEmpty(false);
              }}
              className={`px-3 py-1.5 rounded font-medium border transition-colors ${
                tableError
                  ? 'bg-rose-700 text-white border-rose-700'
                  : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
              }`}
            >
              Error State
            </button>
          </div>
        </div>

        {selectedStudent && (
          <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs flex items-center justify-between text-blue-900">
            <span>
              Selected Row: <strong>{selectedStudent}</strong>
            </span>
            <button
              type="button"
              onClick={() => setSelectedStudent(null)}
              className="text-blue-700 font-bold hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        <DataTable
          columns={tableColumns}
          data={filteredData}
          totalCount={filteredData.length}
          page={tablePage}
          pageSize={tablePageSize}
          onPageChange={setTablePage}
          onPageSizeChange={setTablePageSize}
          isLoading={tableLoading}
          error={tableError ? 'Failed to fetch student enrollment records from database engine.' : null}
          onRetry={() => setTableError(false)}
          searchValue={tableSearch}
          onSearchChange={setTableSearch}
          searchPlaceholder="Search by student name, ID or category..."
          onRowClick={(row) => setSelectedStudent(`${row.name} (${row.id})`)}
          actionSlot={
            <button
              type="button"
              onClick={() => alert('Exporting compliant CSV pursuant to Rule 8...')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-slate-300 bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 shadow-2xs transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export CSV</span>
            </button>
          }
        />
      </section>

      {/* ---------------- 7. Privacy, MaskedValue & Timeline ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-teal-700" />
            7. Privacy, MaskedValue & Audit Timeline
          </h2>
          <p className="text-xs text-slate-500">
            DPDP Act 2023 compliance: unmasking identities requires permission and logs surveillance events.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Masked Values Showcase */}
          <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-2xs space-y-4">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Masked Value Field Variants
            </h3>

            <div className="space-y-3">
              <div>
                <MaskedValue
                  value="987654321012"
                  type="apaar"
                  label="APAAR ID (12-Digit Synthetic)"
                  onRevealLogged={(val) => console.log('Read access logged for APAAR:', val)}
                />
              </div>

              <div>
                <MaskedValue
                  value="9822111222"
                  type="phone"
                  label="Registered Mobile Number"
                />
              </div>

              <div>
                <MaskedValue
                  value="aarav.sharma@coep.ac.in"
                  type="email"
                  label="Official Institutional Email"
                />
              </div>
            </div>
          </div>

          {/* Audit Timeline Showcase */}
          <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-2xs">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">
              Cryptographic Timeline Progression
            </h3>
            <Timeline events={MOCK_TIMELINE} />
          </div>
        </div>
      </section>

      {/* ---------------- 8. ConfirmDialog (Mandatory Reason Input) ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-600" />
            8. ConfirmDialog (Mandatory Reason Requirement)
          </h2>
          <p className="text-xs text-slate-500">
            For critical actions (e.g. revoking a credential or rejecting a seat overflow), reason input is required to enable confirmation.
          </p>
        </div>

        <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-slate-900">Revoke Verifiable Credential</h3>
            <p className="text-xs text-slate-500 max-w-md mt-0.5">
              Revoking marks the credential invalid in the public ledger and sends a signed revocation statement to the employer.
            </p>
            {dialogResult && (
              <p className="text-xs text-emerald-800 font-bold mt-2 bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200 inline-block">
                Success! Action executed with reason: &quot;{dialogResult}&quot;
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="px-4 py-2 bg-rose-700 hover:bg-rose-800 text-white text-xs sm:text-sm font-bold rounded-lg shadow-xs transition-colors shrink-0"
          >
            Trigger Revocation Modal
          </button>

          <ConfirmDialog
            isOpen={dialogOpen}
            title="Revoke Student Credential"
            description="Are you sure you want to revoke credential CRED-IITD-2024-001? This will permanently invalidate all public QR scans."
            confirmLabel="Permanently Revoke"
            variant="danger"
            reasonPlaceholder="Enter AICTE statutory hearing reason or disciplinary order number..."
            onClose={() => setDialogOpen(false)}
            onConfirm={(reason) => {
              setDialogResult(reason);
              setDialogOpen(false);
            }}
          />
        </div>
      </section>

      {/* ---------------- 9. States: Empty, Error & No Permission ---------------- */}
      <section className="space-y-4">
        <div className="border-b border-slate-200 pb-2">
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-slate-500" />
            9. Standalone State Views (Empty, Error, No Permission)
          </h2>
          <p className="text-xs text-slate-500">
            Standardized fallback states utilized across all listings and role boundaries.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <EmptyState
            title="No Applications Pending"
            description="The institutional review queue is currently empty."
            action={{ label: 'Refresh Queue', onClick: () => alert('Queue refreshed') }}
          />

          <ErrorState
            title="Connection Timeout"
            message="National APAAR directory simulation is currently experiencing network latency."
            code={504}
            requestId="REQ-GATEWAY-TIMEOUT-001"
            onRetry={() => alert('Retrying request...')}
          />

          <NoPermissionState
            currentRole="STUDENT"
            requiredRoles={['AICTE_ADMIN', 'AICTE_REVIEWER']}
            onNavigateHome={() => alert('Redirecting to Student Card...')}
          />
        </div>
      </section>
    </div>
  );
};

export default ComponentShowcase;
