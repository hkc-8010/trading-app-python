## **Technical Specification: Rolling ATM Straddle & VWAP Scanner**

### **1. Architecture & API Strategy**

* **Broker Choice:** Both DhanHQ and Zerodha (Kite Connect) are viable, but **DhanHQ** is often preferred for options-heavy scanning because of slightly more liberal data rate limits.

* **Data Ingestion (Critical):** Because we are tracking the **entire NSE F&O universe** (approx. 180+ underlyings), polling REST APIs every minute will hit rate limits and cause latency. The architecture must be **WebSocket-driven**.

* **At 9:15 AM:** Fetch the Master Instrument List once via REST API to map symbols to tokens.

* **Live Data:** Open a WebSocket connection and subscribe strictly to the *Spot/Futures* LTP (Last Traded Price) of all 180+ underlyings.

### **2. The "Rolling ATM" Engine (1-Minute Loop)**

The system needs to dynamically track the At-The-Money (ATM) strike without downloading massive option chains.

* **Calculate ATM Dynamically:** As the WebSocket streams the underlying spot prices, run this calculation every 1 minute for every symbol:

`ATM Strike = Round(Underlying_LTP / Strike_Step) * Strike_Step`

*(e.g., If Nifty Spot is 22030 and the strike step is 50, the ATM = 22000. If Spot moves to 22080, ATM = 22100).*

* **The "Roll" Mechanism:** The script must monitor the Spot price. If the Spot price crosses the threshold into a new ATM territory, the script must dynamically unsubscribe from the old CE/PE WebSocket tokens and subscribe to the new CE/PE tokens.

### **3. VWAP & Straddle Calculation**

The script will resample the incoming tick data into 1-minute pandas DataFrames to calculate the synthetic straddle.

* **Straddle Price:** `CE_LTP + PE_LTP`

* **Straddle Volume:** `CE_Volume + PE_Volume`

* **VWAP Calculation:** Calculate the intraday VWAP for this synthetic instrument cumulatively from 9:15 AM using standard vectorized Pandas functions:

$$VWAP=\frac{\sum(Typical\_Price \times Volume)}{\sum Volume}$$

*(Note: Typical Price = (High + Low + Close) / 3 for that 1-minute candle).*

### **4. The Scanning & Signal Engine**

Run a vectorized scan across the active DataFrame (containing the 180 active straddles) every minute.

* **Signal 1: VWAP Crossover (F&O Universe):**

Trigger an alert/log IF:

`Current 1-Min Straddle Close > Current VWAP` **AND** `Previous 1-Min Straddle Close <= Previous VWAP`

* **Signal 2: Custom User Strikes:**

Maintain a separate configuration file (JSON/Dict) of specific, static strikes provided by the user. Subscribe to these via WebSocket and apply the specific Buy/Sell logic independently of the main universe scanner.

### **5. Visualization & Plotting**

Plotting 180 charts simultaneously using standard Python libraries (like Matplotlib) will crash the application.

* **Dashboard Stack:** Build a lightweight local web dashboard using **Streamlit** or **Dash (by Plotly)**.

* **UI Layout:** Create a dropdown menu to select the underlying ticker (e.g., RELIANCE, NIFTY). When selected, it should fetch the local DataFrame and render an interactive candlestick chart of the calculated Straddle Price overlaid with the VWAP line, updating in near real-time.

When you pass this to your developer, there is one major mathematical decision you need to make regarding the VWAP calculation.

When the underlying price moves and your ATM strike "rolls" to a new strike (e.g., moving from the 22000 straddle to the 22100 straddle), do you want the VWAP calculation to reset to zero for the new strike, or should it continuously carry over the historical volume from the previous strikes to form a single, unbroken synthetic line?