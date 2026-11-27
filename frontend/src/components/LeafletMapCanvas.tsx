"use client";

import React, { useEffect, useRef } from "react";
import type L from "leaflet";
import { AqiBand, AirQualityResponse, LocationOption } from "@/types/dashboard";

export type CityMapDataStatus =
  | "loading"
  | "live-model"
  | "stale-cached"
  | "unavailable"
  | "demo-mode";

export interface CityMapState {
  location: LocationOption;
  status: CityMapDataStatus;
  data: AirQualityResponse | null;
  errorMessage: string | null;
}

interface LeafletMapCanvasProps {
  cities: CityMapState[];
  selectedLocationId: string;
  onSelectLocation: (locationId: string) => void;
}

function getMarkerPalette(
  status: CityMapDataStatus,
  band: AqiBand | null
): { fill: string; stroke: string; text: string } {
  if (status === "demo-mode") {
    return { fill: "#78350F", stroke: "#F59E0B", text: "#FDE68A" };
  }
  if (status === "loading") {
    return { fill: "#1B302D", stroke: "#5EEAD4", text: "#5EEAD4" };
  }
  if (status === "unavailable") {
    return { fill: "#1E293B", stroke: "#94A3B8", text: "#CBD5E1" };
  }

  switch (band) {
    case "Good":
      return { fill: "#065F46", stroke: "#34D399", text: "#ECFDF5" };
    case "Moderate":
      return { fill: "#713F12", stroke: "#FACC15", text: "#FEF9C3" };
    case "Unhealthy for Sensitive Groups":
      return { fill: "#7C2D12", stroke: "#FB923C", text: "#FFEDD5" };
    case "Unhealthy":
      return { fill: "#7F1D1D", stroke: "#F87171", text: "#FEE2E2" };
    case "Very Unhealthy":
    case "Hazardous":
      return { fill: "#581C87", stroke: "#C084FC", text: "#F3E8FF" };
    default:
      return { fill: "#1E293B", stroke: "#94A3B8", text: "#CBD5E1" };
  }
}

export default function LeafletMapCanvas({
  cities,
  selectedLocationId,
  onSelectLocation,
}: LeafletMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const leafletModuleRef = useRef<typeof L | null>(null);

  // Initialize Leaflet map once on client mount (no GPS / geolocation APIs requested)
  useEffect(() => {
    let cancelled = false;

    async function initMap() {
      if (!containerRef.current || mapRef.current) return;
      const leaflet = (await import("leaflet")).default;
      if (cancelled || !containerRef.current) return;

      leafletModuleRef.current = leaflet;

      const map = leaflet.map(containerRef.current, {
        center: [4.5, 18.0],
        zoom: 4,
        minZoom: 3,
        maxZoom: 12,
        zoomControl: true,
        scrollWheelZoom: false,
      });

      // Free, keyless OpenStreetMap standard raster tiles (styled dark via CSS on .leaflet-tile-pane)
      leaflet
        .tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
          maxZoom: 19,
        })
        .addTo(map);

      const layerGroup = leaflet.layerGroup().addTo(map);
      mapRef.current = map;
      markersLayerRef.current = layerGroup;

      // Fit initial bounds nicely across Lagos, Abuja, Nairobi, and Accra
      const bounds = leaflet.latLngBounds(
        cities.map((c) => [c.location.latitude, c.location.longitude] as [number, number])
      );
      map.fitBounds(bounds, { padding: [45, 45], maxZoom: 5 });
    }

    void initMap();

    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        markersLayerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render city markers whenever live/cached/unavailable status or selected city changes
  useEffect(() => {
    const leaflet = leafletModuleRef.current;
    const map = mapRef.current;
    const layerGroup = markersLayerRef.current;
    if (!leaflet || !map || !layerGroup) return;

    layerGroup.clearLayers();

    cities.forEach((cityState) => {
      const { location, status, data } = cityState;
      const isSelected = location.id === selectedLocationId;
      const hasVerifiedAqi =
        (status === "live-model" || status === "stale-cached") &&
        data !== null &&
        data.aqi.status === "available" &&
        data.aqi.value !== null;

      const palette = getMarkerPalette(
        status,
        hasVerifiedAqi ? data?.aqi.band ?? null : null
      );

      const badgeText =
        status === "loading"
          ? "..."
          : status === "demo-mode"
          ? "DEMO"
          : hasVerifiedAqi && data?.aqi.value !== null
          ? String(data.aqi.value)
          : "N/A";

      const ringShadow = isSelected
        ? "0 0 0 4px rgba(94, 234, 212, 0.45), 0 4px 12px rgba(0,0,0,0.6)"
        : "0 2px 8px rgba(0,0,0,0.55)";

      const iconHtml = `
        <div style="display:flex;flex-direction:column;align-items:center;transform:translate(-50%,-50%);cursor:pointer;">
          <div style="
            min-width:44px;
            height:32px;
            padding:0 8px;
            border-radius:9999px;
            background:${palette.fill};
            border:2px solid ${isSelected ? "#5EEAD4" : palette.stroke};
            color:${palette.text};
            font-weight:800;
            font-size:12px;
            display:flex;
            align-items:center;
            justify-content:center;
            box-shadow:${ringShadow};
            white-space:nowrap;
          ">${badgeText}</div>
          <div style="
            margin-top:3px;
            padding:1px 6px;
            border-radius:6px;
            background:rgba(11,20,21,0.92);
            border:1px solid ${isSelected ? "#14B8A6" : "#29423D"};
            color:#F1F5F4;
            font-size:10px;
            font-weight:700;
            white-space:nowrap;
          ">${location.city}</div>
        </div>
      `;

      const icon = leaflet.divIcon({
        className: "airwise-custom-marker",
        html: iconHtml,
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });

      const marker = leaflet.marker([location.latitude, location.longitude], {
        icon,
        title: `${location.display_name} — ${
          hasVerifiedAqi && data
            ? `US AQI ${data.aqi.value} (${data.aqi.band ?? "Model Estimate"})`
            : status === "demo-mode"
            ? "Demo Mode Active (Live Markers Paused)"
            : status === "loading"
            ? "Loading Model Estimate"
            : "Data Unavailable"
        }`,
      });

      const statusLabel =
        status === "live-model"
          ? "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE"
          : status === "stale-cached"
          ? "CACHED / STALE MODEL DATA"
          : status === "demo-mode"
          ? "DEMO MODE (NOT LIVE)"
          : status === "loading"
          ? "LOADING..."
          : "DATA UNAVAILABLE";

      const popupHtml = `
        <div style="min-width:210px;font-size:12px;line-height:1.45;">
          <div style="font-weight:800;font-size:13px;color:#5EEAD4;">${location.display_name}</div>
          <div style="font-size:10px;text-transform:uppercase;color:#A3B8B2;margin-bottom:6px;">${statusLabel}</div>
          <div><strong>US AQI:</strong> ${
            hasVerifiedAqi && data
              ? `${data.aqi.value} (${data.aqi.band ?? "Model"})`
              : "DATA UNAVAILABLE"
          }</div>
          <div><strong>Observation:</strong> ${
            hasVerifiedAqi && data ? `${data.observation_time} (${data.timezone})` : "Unavailable"
          }</div>
          <div style="margin-top:6px;font-size:10px;color:#A3B8B2;">
            CAMS Global ~45 km model grid (not roadside sensor)
          </div>
        </div>
      `;

      marker.bindPopup(popupHtml);
      marker.on("click", () => {
        onSelectLocation(location.id);
      });

      marker.addTo(layerGroup);
    });
  }, [cities, selectedLocationId, onSelectLocation]);

  return (
    <div
      ref={containerRef}
      role="application"
      aria-label="Interactive Africa Air Quality Intelligence Map showing Lagos, Abuja, Nairobi, and Accra"
      className="airwise-leaflet-container w-full h-[360px] sm:h-[420px] rounded-xl border border-theme-border overflow-hidden z-0"
    />
  );
}
