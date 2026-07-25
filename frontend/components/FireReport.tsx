// components/FireReport.tsx
import React from "react";
import { API_BASE_URL } from "../lib/api";

interface FireReportProps {
  pointId: string;
}

const FireReport: React.FC<FireReportProps> = ({ pointId }) => {
  const handleDownload = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/fire-report/${pointId}/`);
      if (!res.ok) throw new Error(`Failed to generate report: ${res.status}`);

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fire_report_${pointId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("❌ Error downloading fire report:", error);
      alert("Failed to download fire report.");
    }
  };

  return (
    <div className="max-w-lg w-full bg-white shadow-lg rounded-2xl p-6 border border-gray-200">
      {/* Header */}
      <div className="border-b border-gray-300 pb-4 mb-4">
        <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
          🔥 Fire Incident Report
        </h2>
        <p className="text-sm text-gray-500 mt-1">
          Download the automatically generated PDF report for this fire point.
        </p>
      </div>

      {/* Fire Point Details */}
      <div className="space-y-2 text-sm text-gray-700">
        <div className="flex justify-between">
          <span className="font-semibold">Point ID:</span>
          <span className="truncate">{pointId}</span>
        </div>
        <div className="flex justify-between">
          <span className="font-semibold">Generated on:</span>
          <span>{new Date().toLocaleDateString()}</span>
        </div>
      </div>

      {/* Button */}
      <div className="mt-6 flex justify-center">
        <button
          onClick={handleDownload}
          className="bg-red-600 hover:bg-red-700 text-white px-5 py-2 rounded-md font-medium transition-all duration-200 shadow-md hover:shadow-lg"
        >
          ⬇️ Download Report
        </button>
      </div>

      {/* Footer */}
      <div className="mt-4 text-xs text-center text-gray-400">
        This report contains geocoded details, nearby fire statistics, and location insights.
      </div>
    </div>
  );
};

export default FireReport;
