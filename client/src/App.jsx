import React, { useState, useEffect, useCallback } from 'react';

// --- Configuration ---
// The configuration is now loaded from the .env file using Vite's import.meta.env
const NODES = [
  {
    name: "Veracity-APPV1", // This name is for display purposes
    url: import.meta.env.VITE_NODE1_URL
  },
  {
    name: "Veracity-APPV2", // This name is for display purposes
    url: import.meta.env.VITE_NODE2_URL
  }
];
const REFRESH_INTERVAL = parseInt(import.meta.env.VITE_REFRESH_INTERVAL, 10) || 5000;

const Spinner = () => (
  <div className="flex justify-center items-center h-64">
    <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-cyan-500"></div>
  </div>
);

const StatusBadge = ({ status }) => {
  const statusStyles = {
    running: 'bg-green-500/20 text-green-400',
    stopped: 'bg-red-500/20 text-red-400',
    starting: 'bg-yellow-500/20 text-yellow-400',
    stopping: 'bg-orange-500/20 text-orange-400',
    paused: 'bg-blue-500/20 text-blue-400',
    unknown: 'bg-gray-500/20 text-gray-400',
  };
  const defaultStyle = 'bg-gray-500/20 text-gray-400';
  const style = statusStyles[status.toLowerCase()] || defaultStyle;
  return (
    <span className={`px-3 py-1 rounded-full text-xs font-semibold leading-tight ${style}`}>
      {status}
    </span>
  );
};

const InstructionModal = ({ instruction, onClose }) => (
  <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex justify-center items-center z-50">
    <div className="bg-gray-800 rounded-lg shadow-2xl p-6 border border-gray-700 max-w-lg w-full">
      <h3 className="text-xl font-bold text-cyan-400 mb-4">Service Instructions</h3>
      <p className="text-gray-300 mb-6 whitespace-pre-wrap">{instruction}</p>
      <button
        onClick={onClose}
        className="bg-cyan-500 text-white font-bold py-2 px-4 rounded-lg hover:bg-cyan-600 transition-colors duration-300"
      >
        Close
      </button>
    </div>
  </div>
);

const ServiceCard = ({ service, onShowInstruction }) => (
  <div className="bg-gray-800/50 backdrop-blur-sm border border-gray-700/50 rounded-lg shadow-lg p-4 flex flex-col justify-between hover:bg-gray-700/50 transition-colors duration-200">
    <div>
      <h3 className="font-bold text-lg text-gray-100 truncate" title={service.display_name}>
        {service.display_name}
      </h3>
      <p className="text-sm text-gray-400 mb-3 truncate" title={service.name}>
        {service.name}
      </p>
    </div>
    <div className="flex justify-between items-center mt-2">
      {service.status.toLowerCase() === 'stopped' && (
        <button
          onClick={() => onShowInstruction(service.instruction)}
          className="text-xs bg-yellow-500/80 text-white font-semibold py-1 px-3 rounded-md hover:bg-yellow-600 transition-colors"
        >
          Instructions
        </button>
      )}
      <div className="flex-grow text-right">
        <StatusBadge status={service.status} />
      </div>
    </div>
  </div>
);

const MachineStatus = ({ machineData, onShowInstruction }) => {
  if (machineData.status === 'offline') {
    return (
      <div className="text-center p-8 bg-red-900/50 rounded-lg shadow-lg col-span-full">
        <h3 className="text-2xl text-red-400 font-bold mb-2">Node Unreachable</h3>
        <p className="text-red-300">Could not connect to the API at {machineData.url}</p>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm-grid-cols-2 md-grid-cols-3 lg-grid-cols-4 xl-grid-cols-5 gap-4">
      {machineData.services.map(service => (
        <ServiceCard key={service.name} service={service} onShowInstruction={onShowInstruction} />
      ))}
    </div>
  );
};

// --- Main App Component ---
function App() {
  const [machineData, setMachineData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [modal, setModal] = useState({ isOpen: false, instruction: '' });

  const fetchNodeData = useCallback(async () => {
    setIsLoading(true);

    const promises = NODES.map(node =>
      fetch(node.url)
        .then(response => {
          if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
          return response.json();
        })
        .then(services => ({ ...node, status: 'online', services }))
        .catch(error => {
          console.error(`Failed to fetch from ${node.name}:`, error);
          return { ...node, status: 'offline', services: [] };
        })
    );

    const results = await Promise.all(promises);
    setMachineData(results);
    setLastUpdated(new Date());
    setIsLoading(false);
  }, []);

  useEffect(() => {
    fetchNodeData();
    const intervalId = setInterval(fetchNodeData, REFRESH_INTERVAL);
    return () => clearInterval(intervalId);
  }, [fetchNodeData]);

  const handleShowInstruction = (instruction) => {
    setModal({ isOpen: true, instruction });
  };

  const handleCloseModal = () => {
    setModal({ isOpen: false, instruction: '' });
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white font-sans p-4 sm:p-6 lg:p-8">
      {modal.isOpen && <InstructionModal instruction={modal.instruction} onClose={handleCloseModal} />}
      <div className="container mx-auto">
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
            <div>
              <h1 className="text-4xl font-bold text-cyan-400">Cluster Service Dashboard</h1>
              <p className="text-gray-400">Live status of services on all cluster nodes.</p>
            </div>
            <div className="flex items-center gap-4">
              {lastUpdated && (
                <div className="text-right text-sm text-gray-500">
                   Last updated: {lastUpdated.toLocaleTimeString()}
                </div>
              )}
              <button
                onClick={fetchNodeData}
                disabled={isLoading}
                className="bg-cyan-500 text-white font-bold py-2 px-4 rounded-lg hover:bg-cyan-600 transition-colors duration-300 disabled:bg-gray-600 disabled:cursor-not-allowed flex items-center gap-2"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className={`h-5 w-5 ${isLoading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h5M20 20v-5h-5M4 4l16 16" />
                </svg>
                {isLoading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
          </div>
        </header>

        {/* MODIFIED: Changed main to a grid for side-by-side layout on large screens */}
        <main className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">
          {isLoading && machineData.length === 0 ? <Spinner /> :
            machineData.map(machine => (
              <section key={machine.name}>
                <h2 className="text-3xl font-bold text-cyan-400 border-b-2 border-cyan-800/50 pb-2 mb-6">
                  {machine.name}
                </h2>
                <MachineStatus machineData={machine} onShowInstruction={handleShowInstruction} />
              </section>
            ))
          }
        </main>
      </div>
    </div>
  );
}

export default App;