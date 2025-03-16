// slack.js

// TODO
import React, { useState } from "react";
import axios from "axios";

export const HubSpotIntegration = ({ userId, orgId }) => {
    const [isConnected, setIsConnected] = useState(false);

    const handleConnect = async () => {
        try {
            const response = await axios.post("http://localhost:8000/integrations/hubspot/authorize", {
                user_id: userId,
                org_id: orgId,
            });
            const authUrl = response.data;
            window.open(authUrl, "_blank", "width=600,height=600");
        } catch (error) {
            console.error("Error connecting to HubSpot:", error);
        }
    };

    return (
        <div>
            <button onClick={handleConnect} disabled={isConnected}>
                {isConnected ? "Connected to HubSpot" : "Connect to HubSpot"}
            </button>
        </div>
    );
};