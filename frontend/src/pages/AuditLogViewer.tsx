import React, { useEffect, useState } from 'react';
import { Lock, Shield, RefreshCw, Filter, Search } from 'lucide-react';
import { AuditEvent } from '../types';
import { getAuditEvents } from '../services/api';

export const AuditLogViewer: React.FC = () => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [filterQuery, setFilterQuery] = useState<string>('');

  const fetchEvents = async () => {
    try {
      setLoading(true);
      const data = await getAuditEvents(100);
      setEvents(data);
    } catch (err) {
      console.error('Error fetching audit events:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, []);

  const filteredEvents = events.filter((e) => {
    const q = filterQuery.toLowerCase();
    return (
      e.action.toLowerCase().includes(q) ||
      e.actor_id.toLowerCase().includes(q) ||
      e.actor_role.toLowerCase().includes(q) ||
      e.entity_type.toLowerCase().includes(q) ||
      e.reason.toLowerCase().includes(q) ||
      e.request_id.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-xl font-bold text-slate-900 flex items-center space-x-2">
              <Lock className="w-5 h-5 text-indigo-600" />
              <span>Immutable Audit Trail (Rule 9)</span>
            </h1>
            <span className="bg-indigo-50 text-indigo-800 text-xs px-2.5 py-0.5 rounded-full font-semibold border border-indigo-200">
              Auditor View
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Rule 9: Every state change writes an audit event (actor, action, entity, reason, timestamp, request_id).
          </p>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              placeholder="Search audit trail..."
              className="pl-8 pr-3 py-1.5 text-xs border border-slate-300 rounded-lg bg-white"
            />
          </div>
          <button
            onClick={fetchEvents}
            className="p-2 border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-lg text-xs"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center p-12">
            <RefreshCw className="w-6 h-6 animate-spin text-indigo-600" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-5 py-3">Timestamp (UTC)</th>
                  <th className="px-5 py-3">Request ID</th>
                  <th className="px-5 py-3">Actor & Role</th>
                  <th className="px-5 py-3">Action</th>
                  <th className="px-5 py-3">Entity</th>
                  <th className="px-5 py-3">Statutory Justification / Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredEvents.map((evt) => (
                  <tr key={evt.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-5 py-3 font-mono text-slate-500 whitespace-nowrap">
                      {new Date(evt.created_at).toLocaleString()}
                    </td>
                    <td className="px-5 py-3 font-mono text-blue-900 font-semibold whitespace-nowrap">
                      {evt.request_id}
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap">
                      <span className="font-medium text-slate-900 block">{evt.actor_id}</span>
                      <span className="text-[10px] text-slate-500 font-semibold">{evt.actor_role}</span>
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap">
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-800 border border-slate-200">
                        {evt.action}
                      </span>
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap">
                      <span className="text-slate-800 font-semibold block">{evt.entity_type}</span>
                      <span className="font-mono text-[10px] text-slate-500">{evt.entity_id}</span>
                    </td>
                    <td className="px-5 py-3 text-slate-700 max-w-md">
                      {evt.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
