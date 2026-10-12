#region Using declarations
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    internal sealed class GateOrderEnforcer
    {
        private readonly GateRuntime runtime;

        public GateOrderEnforcer(GateRuntime runtime)
        {
            this.runtime = runtime;
        }

        public void SubscribeAll()
        {
        }

        public void Stop()
        {
        }

        public void MarkGateEntry(long orderId)
        {
        }
    }
}
