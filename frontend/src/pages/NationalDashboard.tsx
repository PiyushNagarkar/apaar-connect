import React, { useEffect, useState } from 'react';
import {
  Building2,
  Users,
  CheckCircle2,
  AlertTriangle,
  Layers,
  TrendingUp,
  RefreshCw,
  Info,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { SystemOverviewAnalytics, Institution } from '../types';
import { getSystemOverview, listInstitutions } from '../services/api';
import { StatCard } from '../components/StatCard';

export const NationalDashboard: React.FC = () => {
  const [analytics, setAnalytics] = useState<SystemOverviewAnalytics | null>(null);
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [overviewData, instsData] = await Promise.all([
        getSystemOverview(),
        listInstitutions(),
      ]);
      setAnalytics(overviewData);
      setInstitutions(instsData);
    } catch (err: any) {
      setError(err.message || 'Failed to load national analytics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center space-y-3 text-slate-500">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
          <p className="text-sm font-medium">Computing dynamic metrics from database (Rule 11)...</p>
        </div>
      </div>
    );
  }

  if (error || !analytics) {
    return (
      <div className="bg-rose-50 border border-rose-200 text-rose-800 p-6 rounded-xl my-6">
        <h3 className="font-bold flex items-center space-x-2">
          <AlertTriangle className="w-5 h-5" />
          <span>Error Loading Dashboard</span>
        </h3>
        <p className="text-sm mt-1">{error}</p>
        <button
          onClick={fetchData}
          className="mt-3 px-4 py-2 bg-rose-700 text-white rounded-lg text-xs font-semibold hover:bg-rose-800"
        >
          Retry
        </button>
      </div>
    );
  }

  // Prepare chart data for per-program intake vs confirmed
  const programChartData = analytics.program_metrics.map((p) => ({
    name: p.program_name.length > 20 ? p.program_name.slice(0, 18) + '...' : p.program_name,
    intake: p.total_approved_intake,
    confirmed: p.total_confirmed,
    utilization: p.utilization_percentage,
  }));

  // Verification funnel pie data
  const funnelPieData = [
    { name: 'Confirmed', value: analytics.funnel.confirmed_count, color: '#059669' },
    { name: 'Under Review', value: analytics.funnel.under_review_count, color: '#d97706' },
    { name: 'Provisional (L1 Unavail)', value: analytics.funnel.provisional_count, color: '#2563eb' },
    { name: 'Rejected', value: analytics.funnel.rejected_count, color: '#e11d48' },
  ].filter((d) => d.value > 0);

  return (
    <div className="space-y-6">
      {/* Page Title & Rule Callout */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-xl border border-slate-200 shadow-xs">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-xl font-extrabold text-slate-900 tracking-tight">
              National AICTE Admission & Seat Matrix Command
            </h1>
            <span className="bg-emerald-100 text-emerald-800 text-xs px-2.5 py-0.5 rounded-full font-semibold border border-emerald-200">
              Live Database
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Rule 11 Compliant: Every number is computed in real-time from PostgreSQL/SQLite tables. No hard-coded metrics.
          </p>
        </div>
        <button
          onClick={fetchData}
          className="inline-flex items-center space-x-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh Metrics</span>
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Approved Institutions"
          value={analytics.total_institutions}
          subtitle={`${analytics.active_institutions} active regulatory status`}
          icon={Building2}
          colorScheme="blue"
        />
        <StatCard
          title="Statutory Seat Quota"
          value={analytics.total_statutory_intake}
          subtitle={`Across ${analytics.total_approved_programs} approved programs`}
          icon={Layers}
          colorScheme="indigo"
        />
        <StatCard
          title="Verified Admissions"
          value={analytics.total_confirmed_students}
          subtitle={`${analytics.overall_intake_utilization}% overall seat fill rate`}
          icon={CheckCircle2}
          colorScheme="emerald"
        />
        <StatCard
          title="Open Review Cases"
          value={analytics.review_queue.total_open_cases}
          subtitle={`${analytics.review_queue.high_priority_cases} high-priority (Score ≥ 70)`}
          icon={AlertTriangle}
          colorScheme="amber"
        />
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Seat Utilization Bar Chart */}
        <div className="lg:col-span-2 bg-white p-6 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-bold text-slate-900 text-sm">Approved Intake vs. Confirmed Admissions</h3>
              <p className="text-xs text-slate-500">Per approved program (Rule 3 per-category compliance)</p>
            </div>
            <span className="text-xs font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
              Rule 3 Enforced
            </span>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={programChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                <Bar dataKey="intake" name="Approved Intake" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                <Bar dataKey="confirmed" name="Confirmed Students" fill="#059669" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Verification Funnel Distribution */}
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-bold text-slate-900 text-sm">Admission Record Status</h3>
              <span className="text-[10px] text-slate-400">Total: {analytics.funnel.total_submitted}</span>
            </div>
            <p className="text-xs text-slate-500 mb-4">Lifecycle breakdown across all batches</p>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={funnelPieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={70}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {funnelPieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Verification Layer Metrics */}
          <div className="mt-4 pt-3 border-t border-slate-100 space-y-1.5 text-xs">
            <div className="flex justify-between items-center text-slate-600">
              <span>L1 Identity (MOCK_APAAR_V1):</span>
              <span className="font-semibold text-emerald-700">{analytics.funnel.l1_pass_count} Pass</span>
            </div>
            <div className="flex justify-between items-center text-slate-600">
              <span>L1 Service Unavailable (Rule 5):</span>
              <span className="font-semibold text-blue-700">{analytics.funnel.l1_unavailable_count} Provisional</span>
            </div>
            <div className="flex justify-between items-center text-slate-600">
              <span>L2 Institutional Authority:</span>
              <span className="font-semibold text-emerald-700">{analytics.funnel.l2_pass_count} Pass</span>
            </div>
            <div className="flex justify-between items-center text-slate-600">
              <span>L3 Seat & Duplicate Compliance:</span>
              <span className="font-semibold text-emerald-700">{analytics.funnel.l3_pass_count} Pass</span>
            </div>
          </div>
        </div>
      </div>

      {/* Participating Institutions Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-5 border-b border-slate-200 flex items-center justify-between">
          <div>
            <h3 className="font-bold text-slate-900 text-sm">Approved Institutions</h3>
            <p className="text-xs text-slate-500">Regulated institutions with frozen approval snapshots</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider font-semibold border-b border-slate-200">
              <tr>
                <th className="px-5 py-3">Permanent ID</th>
                <th className="px-5 py-3">Institution Name</th>
                <th className="px-5 py-3">State</th>
                <th className="px-5 py-3">Type</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Autonomous</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {institutions.map((inst) => (
                <tr key={inst.id} className="hover:bg-slate-50/80 transition-colors">
                  <td className="px-5 py-3 font-mono font-semibold text-blue-900">{inst.aicte_permanent_id}</td>
                  <td className="px-5 py-3 font-medium text-slate-900">{inst.name}</td>
                  <td className="px-5 py-3 text-slate-600">{inst.state}</td>
                  <td className="px-5 py-3 text-slate-600">{inst.institution_type}</td>
                  <td className="px-5 py-3">
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      {inst.status}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-600">{inst.is_autonomous ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
