"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { AssetClass, Instrument } from "@/lib/types";

const ASSET_CLASSES: AssetClass[] = [
  "cash",
  "equity",
  "etf",
  "bond",
  "fund",
  "real_estate",
  "private_equity",
  "company_equity",
  "gold",
  "crypto",
  "custom",
  "liability",
];

export function AddHoldingDialog({ accountId }: { accountId: string }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [creatingNew, setCreatingNew] = useState(false);
  const [instrumentId, setInstrumentId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [newInstrument, setNewInstrument] = useState({
    name: "",
    symbol: "",
    asset_class: "equity" as AssetClass,
    currency: "USD",
  });

  const instrumentsQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
    enabled: open,
  });

  const reset = () => {
    setInstrumentId("");
    setQuantity("");
    setCreatingNew(false);
    setNewInstrument({ name: "", symbol: "", asset_class: "equity", currency: "USD" });
  };

  const mutation = useMutation({
    mutationFn: async () => {
      let targetInstrumentId = instrumentId;
      if (creatingNew) {
        const created = await api.post<Instrument>("/api/instruments", {
          name: newInstrument.name,
          symbol: newInstrument.symbol || null,
          asset_class: newInstrument.asset_class,
          currency: newInstrument.currency.toUpperCase(),
          price_source_type:
            newInstrument.asset_class === "cash"
              ? "fx_derived"
              : ["equity", "etf", "fund", "crypto", "gold"].includes(newInstrument.asset_class)
                ? "market"
                : "manual",
        });
        targetInstrumentId = created.id;
      }
      return api.put("/api/holdings", {
        account_id: accountId,
        instrument_id: targetInstrumentId,
        quantity,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts", accountId, "holdings"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["instruments"] });
      toast.success(t("common.saved"));
      setOpen(false);
      reset();
    },
    onError: () => toast.error(t("common.error")),
  });

  const canSubmit =
    quantity.trim() !== "" && (creatingNew ? newInstrument.name.trim() !== "" : instrumentId !== "");

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger
        render={
          <Button size="sm" variant="outline">
            {t("accounts.add_holding")}
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("accounts.add_holding")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {!creatingNew ? (
            <div className="space-y-1.5">
              <Label>{t("accounts.instrument")}</Label>
              <Select value={instrumentId} onValueChange={(v) => setInstrumentId(v ?? "")}>
                <SelectTrigger>
                  <SelectValue placeholder={t("accounts.select_instrument")} />
                </SelectTrigger>
                <SelectContent>
                  {(instrumentsQuery.data ?? []).map((inst) => (
                    <SelectItem key={inst.id} value={inst.id}>
                      {inst.symbol ? `${inst.symbol} · ${inst.name}` : inst.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <button
                type="button"
                className="text-xs text-muted-foreground underline"
                onClick={() => setCreatingNew(true)}
              >
                {t("accounts.create_new_instrument")}
              </button>
            </div>
          ) : (
            <div className="space-y-3 rounded-md border p-3">
              <div className="space-y-1.5">
                <Label>{t("accounts.name")}</Label>
                <Input
                  value={newInstrument.name}
                  onChange={(e) => setNewInstrument((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>{t("accounts.symbol")}</Label>
                  <Input
                    value={newInstrument.symbol}
                    onChange={(e) => setNewInstrument((f) => ({ ...f, symbol: e.target.value.toUpperCase() }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{t("accounts.currency")}</Label>
                  <Input
                    maxLength={3}
                    value={newInstrument.currency}
                    onChange={(e) => setNewInstrument((f) => ({ ...f, currency: e.target.value.toUpperCase() }))}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>{t("accounts.asset_class")}</Label>
                <Select
                  value={newInstrument.asset_class}
                  onValueChange={(v) => setNewInstrument((f) => ({ ...f, asset_class: v as AssetClass }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ASSET_CLASSES.map((cls) => (
                      <SelectItem key={cls} value={cls}>
                        {cls}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <button
                type="button"
                className="text-xs text-muted-foreground underline"
                onClick={() => setCreatingNew(false)}
              >
                {t("common.cancel")}
              </button>
            </div>
          )}

          <div className="space-y-1.5">
            <Label>{t("accounts.quantity")}</Label>
            <Input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="decimal" />
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!canSubmit || mutation.isPending} onClick={() => mutation.mutate()}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
