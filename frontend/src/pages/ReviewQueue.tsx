import React, { useEffect, useState } from 'react';
import {
  FileSearch,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ArrowRight,
  ShieldAlert,
  Sparkles,
  RefreshCw,
  Scale,
  Eye,
  X,
} from 'lucide-react';
import { ReviewCase } from '../types';
import { listReviewCases, resolveReviewCase } from '../services/api';

export const ReviewQueue: React.FC = () => {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [filterStatus, setFilterStatus] = useState<string>('OPEN');
  const [selectedCase, setSelectedCase] = useState<ReviewCase | null>(null);
  const [resolutionModalOpen, setResolutionModalOpen] = useState<boolean>(false);
  const [resolutionChoice, setResolutionChoice] = useState<'CONFIRMED' | 'PROVISIONAL' | 'REJECTED'>('CONFIRMED');
  const [resolutionReason, setResolutionReason] = useState<string>('');
  const [resolving, setResolving] = useState<boolean>(false);

  const fetchCases = async () => {
    try {
      setLoading(true);
      const data = await listReviewCases(filterStatus);
      setCases(data);
    } catch (err) {
      console.error('Error fetching review cases:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCases();
  }, [filterStatus]);

  const handleResolve = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCase || !resolutionReason.trim()) return;

    try {
      setResolving(true);
      await resolveReviewCase(selectedCase.id, resolutionChoice, resolutionReason);
      setResolutionModalOpen(false);
      setSelectedCase(null);
      setResolutionReason('');
      await fetchCases();
    } catch (err: any) {
      alert(`Resolution failed: ${err.message}`);
    } finally {
      setResolving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Title & Rules Banner */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-xl font-bold text-slate-900 flex items-center space-x-2">
              <Scale className="w-5 h-5 text-amber-600" />
              <span>Human Review & Adjudication Queue</span>
            </h1>
            <span className="bg-amber-100 text-amber-800 text-xs px-2.5 py-0.5 rounded-full font-semibold border border-amber-200">
              Rule 4 & 6 Enforced
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Rule 4: Exception matches never auto-reject or auto-accuse. Rule 6: Scores only prioritize human inspection and display transparent reason codes.
          </p>
        </div>

        {/* Filter Controls */}
        <div className="flex items-center space-x-2 shrink-0">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="text-xs border border-slate-300 rounded-lg px-3 py-1.5 bg-white font-medium text-slate-700"
          >
            <option value="OPEN">Open Cases</option>
            <option value="RESOLVED">Resolved Cases</option>
            <option value="ALL">All Cases</option>
          </select>
          <button
            onClick={fetchCases}
            className="p-2 border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-lg text-xs"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Cases List */}
      {loading ? (
        <div className="flex items-center justify-center min-h-[300px]">
          <RefreshCw className="w-8 h-8 animate-spin text-amber-600" />
        </div>
      ) : cases.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
          <h3 className="font-bold text-slate-900 text-base">No Open Exceptions in Queue</h3>
          <p className="text-xs text-slate-500 mt-1">
            All submitted admission records have passed verification or have been adjudicated.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {cases.map((c) => {
            const isHighPriority = c.priority_score >= 70;
            return (
              <div
                key={c.id}
                className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs hover:border-slate-300 transition-all flex flex-col lg:flex-row lg:items-center justify-between gap-4"
              >
                <div className="space-y-2 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-bold text-xs text-blue-900 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                      {c.id}
                    </span>
                    <span className="font-semibold text-xs px-2.5 py-0.5 rounded-full uppercase bg-slate-100 text-slate-700">
                      {c.case_type.replace(/_/g, ' ')}
                    </span>
                    <span
                      className={`font-bold text-xs px-2.5 py-0.5 rounded-full ${
                        isHighPriority
                          ? 'bg-rose-50 text-rose-800 border border-rose-200'
                          : 'bg-amber-50 text-amber-800 border border-amber-200'
                      }`}
                    >
                      Priority Score: {c.priority_score}/100
                    </span>
                    <span className="text-xs text-slate-400">• Institution: {c.institution_id}</span>
                  </div>

                  {/* Explainable Score Breakdown (Rule 6) */}
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs">
                    <p className="font-semibold text-slate-800 mb-1.5 flex items-center space-x-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-amber-600" />
                      <span>Transparent Priority Breakdown (Rule 6):</span>
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(c.score_breakdown).map(([component, weight]) => (
                        <span
                          key={component}
                          className="px-2 py-0.5 rounded bg-white border border-slate-200 font-mono text-[11px] text-slate-700"
                        >
                          {component}: <strong className="text-slate-900">+{weight} pts</strong>
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Reason Codes */}
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="text-slate-500 font-semibold">Reason Codes:</span>
                    {c.reason_codes.map((code) => (
                      <span key={code} className="px-2 py-0.5 bg-slate-100 text-slate-700 rounded font-mono">
                        {code}
                      </span>
                    ))}
                  </div>

                  {/* Duplicate Conflict Match Evidence (Rule 4) */}
                  {c.match_evidence?.conflicting_records && c.match_evidence.conflicting_records.length > 0 && (
                    <div className="bg-amber-50/60 border border-amber-200 rounded-lg p-2.5 text-xs">
                      <p className="font-semibold text-amber-900 mb-1">
                        Cross-Institution Duplicate Collision Match:
                      </p>
                      <ul className="space-y-1 text-slate-700">
                        {c.match_evidence.conflicting_records.map((conflict, i) => (
                          <li key={i} className="flex items-center space-x-2 font-mono text-[11px]">
                            <span>• Institution: <strong className="text-slate-900">{conflict.institution_id}</strong></span>
                            <span>| Record: {conflict.record_id}</span>
                            <span>| Masked APAAR: {conflict.masked_apaar}</span>
                            <span>| Status: {conflict.status}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Resolution Details if already resolved */}
                  {c.status === 'RESOLVED' && (
                    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-2.5 text-xs text-emerald-950">
                      <p className="font-semibold">
                        Resolved as: <span className="uppercase font-bold">{c.resolution}</span> on{' '}
                        {c.resolved_at ? new Date(c.resolved_at).toLocaleString() : ''}
                      </p>
                      <p className="italic text-emerald-800 mt-0.5">"{c.resolution_reason}"</p>
                    </div>
                  )}
                </div>

                {/* Action Buttons */}
                <div className="flex lg:flex-col items-center justify-end gap-2 shrink-0 border-t lg:border-t-0 lg:border-l border-slate-100 pt-3 lg:pt-0 lg:pl-4">
                  {c.status === 'OPEN' ? (
                    <button
                      onClick={() => {
                        setSelectedCase(c);
                        setResolutionModalOpen(true);
                      }}
                      className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg text-xs shadow-xs transition-colors"
                    >
                      Adjudicate Case
                    </button>
                  ) : (
                    <span className="text-xs font-semibold text-slate-500">Adjudicated</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Adjudication Modal */}
      {resolutionModalOpen && selectedCase && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-6 border border-slate-200 text-xs">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="font-bold text-slate-900 text-base">Human Adjudication Decision</h3>
              <button onClick={() => setResolutionModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleResolve} className="space-y-4 mt-4">
              <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 space-y-1">
                <p className="text-slate-500">Case ID: <span className="font-mono font-bold text-slate-900">{selectedCase.id}</span></p>
                <p className="text-slate-500">Type: <span className="font-semibold text-slate-900">{selectedCase.case_type}</span></p>
                <p className="text-slate-500">Student Record: <span className="font-mono text-slate-900">{selectedCase.student_record_id}</span></p>
              </div>

              <div>
                <label className="block font-semibold text-slate-800 mb-2">Resolution Action:</label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setResolutionChoice('CONFIRMED')}
                    className={`p-2.5 rounded-lg border text-center font-bold transition-all ${
                      resolutionChoice === 'CONFIRMED'
                        ? 'bg-emerald-50 border-emerald-500 text-emerald-800 ring-1 ring-emerald-500'
                        : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    Confirm (Pass)
                  </button>
                  <button
                    type="button"
                    onClick={() => setResolutionChoice('PROVISIONAL')}
                    className={`p-2.5 rounded-lg border text-center font-bold transition-all ${
                      resolutionChoice === 'PROVISIONAL'
                        ? 'bg-blue-50 border-blue-500 text-blue-800 ring-1 ring-blue-500'
                        : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    Provisional
                  </button>
                  <button
                    type="button"
                    onClick={() => setResolutionChoice('REJECTED')}
                    className={`p-2.5 rounded-lg border text-center font-bold transition-all ${
                      resolutionChoice === 'REJECTED'
                        ? 'bg-rose-50 border-rose-500 text-rose-800 ring-1 ring-rose-500'
                        : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    Reject
                  </button>
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-800 mb-1">
                  Mandatory Audit Justification (Rule 9):
                </label>
                <textarea
                  required
                  rows={3}
                  value={resolutionReason}
                  onChange={(e) => setResolutionReason(e.target.value)}
                  placeholder="State clear statutory reason for decision (e.g., Verified NOC from previous institution or confirmed supernumerary quota approval)..."
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs"
                />
              </div>

              <div className="pt-3 border-t border-slate-200 flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={() => setResolutionModalOpen(false)}
                  className="px-4 py-2 border border-slate-300 rounded-lg text-slate-700 hover:bg-slate-50 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={resolving || !resolutionReason.trim()}
                  className="px-4 py-2 bg-blue-900 text-white font-semibold rounded-lg hover:bg-blue-800 disabled:opacity-50"
                >
                  {resolving ? 'Recording Adjudication...' : 'Submit Resolution'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
