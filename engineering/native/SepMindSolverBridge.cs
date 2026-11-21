// SepMind developer-owned bridge, Apache-2.0.
// Numerical callbacks only; no user source code or dynamic expression execution.
using System;
using DWSIM.Interfaces;

namespace SepMind.Native {
    public delegate double[] NonlinearCallback(
        Func<double[], double[]> function,
        Func<double[], double[,]> gradient,
        Func<double[], double[], bool> iteration,
        double[] initial, int iterations, double tolerance);

    public sealed class NonlinearBridge : IExternalNonLinearSystemSolver, IExternalSolverIdentification {
        public string ID { get { return "sepmind_sparse_trust_region_v1"; } }
        public string Description { get { return "Sparse numerical solution of native DWSIM MESH residuals"; } }
        public string DisplayText { get { return "SepMind sparse trust region"; } }
        public bool SupportsMultiThreading { get { return false; } }
        public DWSIM.Interfaces.Enums.ExternalSolverCategory Category {
            get {
                foreach (string name in Enum.GetNames(typeof(DWSIM.Interfaces.Enums.ExternalSolverCategory)))
                    if (name.ToLowerInvariant().Contains("nonlinear"))
                        return (DWSIM.Interfaces.Enums.ExternalSolverCategory)Enum.Parse(typeof(DWSIM.Interfaces.Enums.ExternalSolverCategory), name);
                throw new InvalidOperationException("Native nonlinear category is unavailable");
            }
        }
        public NonlinearCallback Callback { get; set; }
        public double[] Solve(Func<double[], double[]> function,
            Func<double[], double[,]> gradient,
            Func<double[], double[], bool> iteration,
            double[] initial, int iterations, double tolerance) {
            if (Callback == null) throw new InvalidOperationException("Registered numerical callback required");
            return Callback(function, gradient, iteration, initial, iterations, tolerance);
        }
    }
}
