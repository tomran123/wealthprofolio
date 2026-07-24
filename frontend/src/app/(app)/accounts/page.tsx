"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { AddHoldingDialog } from "@/components/add-holding-dialog";
import {
  ListSkeleton,
  LoadingSpinner,
  TableSkeleton,
} from "@/components/loading-state";
import { SetValuationDialog } from "@/components/set-valuation-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { formatMoney, formatNumber } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type {
  AccountWithNames,
  HoldingWithInstrument,
  Institution,
  Owner,
} from "@/lib/types";

export default function AccountsPage() {
  const { t } = useI18n();
  return (
    <Tabs defaultValue="accounts" className="space-y-4">
      <TabsList>
        <TabsTrigger value="accounts">{t("accounts.tab_accounts")}</TabsTrigger>
        <TabsTrigger value="institutions">
          {t("accounts.tab_institutions")}
        </TabsTrigger>
        <TabsTrigger value="owners">{t("accounts.tab_owners")}</TabsTrigger>
      </TabsList>
      <TabsContent value="accounts">
        <AccountsTab />
      </TabsContent>
      <TabsContent value="institutions">
        <InstitutionsTab />
      </TabsContent>
      <TabsContent value="owners">
        <OwnersTab />
      </TabsContent>
    </Tabs>
  );
}

function AccountsTab() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    institution_id: "",
    owner_id: "",
    account_type: "brokerage",
    base_currency: "USD",
  });

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<AccountWithNames[]>("/api/accounts"),
  });
  const institutionsQuery = useQuery({
    queryKey: ["institutions"],
    queryFn: () => api.get<Institution[]>("/api/institutions"),
  });
  const ownersQuery = useQuery({
    queryKey: ["owners"],
    queryFn: () => api.get<Owner[]>("/api/owners"),
  });

  const holdingsQuery = useQuery({
    queryKey: ["accounts", expandedId, "holdings"],
    queryFn: () =>
      api.get<HoldingWithInstrument[]>(`/api/accounts/${expandedId}/holdings`),
    enabled: !!expandedId,
  });

  const createMutation = useMutation({
    mutationFn: () => api.post<AccountWithNames>("/api/accounts", form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setOpen(false);
      setForm({
        name: "",
        institution_id: "",
        owner_id: "",
        account_type: "brokerage",
        base_currency: "USD",
      });
      toast.success(t("common.saved"));
    },
    onError: () => toast.error(t("common.error")),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger
            render={<Button>{t("accounts.add_account")}</Button>}
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("accounts.add_account")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t("accounts.name")}</Label>
                <Input
                  value={form.name}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, name: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("accounts.institution")}</Label>
                <Select
                  value={form.institution_id}
                  onValueChange={(v) =>
                    setForm((f) => ({ ...f, institution_id: v ?? "" }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={t("accounts.select_institution")}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {(institutionsQuery.data ?? []).map((inst) => (
                      <SelectItem key={inst.id} value={inst.id}>
                        {inst.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>{t("accounts.owner")}</Label>
                <Select
                  value={form.owner_id}
                  onValueChange={(v) =>
                    setForm((f) => ({ ...f, owner_id: v ?? "" }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("accounts.select_owner")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(ownersQuery.data ?? []).map((owner) => (
                      <SelectItem key={owner.id} value={owner.id}>
                        {owner.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>{t("accounts.type")}</Label>
                  <Select
                    value={form.account_type}
                    onValueChange={(v) =>
                      setForm((f) => ({ ...f, account_type: v ?? "brokerage" }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="cash">Cash</SelectItem>
                      <SelectItem value="brokerage">Brokerage</SelectItem>
                      <SelectItem value="mixed">Mixed</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>{t("accounts.base_currency")}</Label>
                  <Input
                    value={form.base_currency}
                    maxLength={3}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        base_currency: e.target.value.toUpperCase(),
                      }))
                    }
                  />
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={
                  !form.name ||
                  !form.institution_id ||
                  !form.owner_id ||
                  createMutation.isPending
                }
                aria-busy={createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending && (
                  <LoadingSpinner label={t("common.loading")} />
                )}
                {createMutation.isPending
                  ? t("common.loading")
                  : t("common.save")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card aria-busy={accountsQuery.isLoading}>
        <CardContent className="pt-6">
          {accountsQuery.isLoading ? (
            <TableSkeleton
              columns={5}
              rows={6}
              label={t("common.loading")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("accounts.name")}</TableHead>
                  <TableHead>{t("accounts.institution")}</TableHead>
                  <TableHead>{t("accounts.owner")}</TableHead>
                  <TableHead>{t("accounts.type")}</TableHead>
                  <TableHead>{t("accounts.base_currency")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(accountsQuery.data ?? []).map((account) => (
                  <Fragment key={account.id}>
                    <TableRow
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() =>
                        setExpandedId(
                          expandedId === account.id ? null : account.id,
                        )
                      }
                    >
                      <TableCell className="font-medium">
                        {account.name}
                      </TableCell>
                      <TableCell>{account.institution_name}</TableCell>
                      <TableCell>{account.owner_name}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">
                          {account.account_type}
                        </Badge>
                      </TableCell>
                      <TableCell>{account.base_currency}</TableCell>
                    </TableRow>
                    {expandedId === account.id && (
                      <TableRow className="bg-muted/30">
                        <TableCell colSpan={5}>
                          <div className="space-y-2 py-2">
                            <div className="flex justify-end">
                              <AddHoldingDialog accountId={account.id} />
                            </div>
                            {holdingsQuery.isLoading ? (
                              <ListSkeleton
                                compact
                                rows={3}
                                label={t("common.loading")}
                              />
                            ) : (holdingsQuery.data ?? []).length === 0 ? (
                              <p className="py-2 text-sm text-muted-foreground">
                                {t("accounts.no_holdings")}
                              </p>
                            ) : (
                              <div className="space-y-1">
                                {(holdingsQuery.data ?? []).map((h) => (
                                  <div
                                    key={h.id}
                                    className="flex items-center justify-between text-sm"
                                  >
                                    <div>
                                      <div className="font-medium">
                                        {h.instrument_symbol ??
                                          h.instrument_name}
                                      </div>
                                      <div className="text-xs text-muted-foreground">
                                        {h.price !== null && h.price_currency
                                          ? `${t("accounts.price")} ${formatMoney(h.price, h.price_currency)} · ${t("accounts.market_value")} ${formatMoney(h.market_value ?? 0, h.price_currency)}`
                                          : t("accounts.price_unavailable")}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <span className="text-muted-foreground">
                                        {formatNumber(h.quantity)}
                                      </span>
                                      {h.price_source_type === "manual" && (
                                        <SetValuationDialog
                                          instrumentId={h.instrument_id}
                                          defaultCurrency={
                                            account.base_currency
                                          }
                                          trigger={
                                            <Button
                                              size="sm"
                                              variant="ghost"
                                              className="h-6 px-2 text-xs"
                                            >
                                              {t("accounts.set_price")}
                                            </Button>
                                          }
                                        />
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function InstitutionsTab() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    institution_type: "bank",
    country: "",
  });

  const query = useQuery({
    queryKey: ["institutions"],
    queryFn: () => api.get<Institution[]>("/api/institutions"),
  });
  const createMutation = useMutation({
    mutationFn: () =>
      api.post<Institution>("/api/institutions", {
        ...form,
        country: form.country || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["institutions"] });
      setOpen(false);
      setForm({ name: "", institution_type: "bank", country: "" });
      toast.success(t("common.saved"));
    },
    onError: () => toast.error(t("common.error")),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger
            render={<Button>{t("accounts.add_institution")}</Button>}
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("accounts.add_institution")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t("accounts.name")}</Label>
                <Input
                  value={form.name}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, name: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("accounts.type")}</Label>
                <Select
                  value={form.institution_type}
                  onValueChange={(v) =>
                    setForm((f) => ({ ...f, institution_type: v ?? "bank" }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bank">Bank</SelectItem>
                    <SelectItem value="broker">Broker</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>{t("accounts.country")}</Label>
                <Input
                  value={form.country}
                  maxLength={2}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      country: e.target.value.toUpperCase(),
                    }))
                  }
                  placeholder="US / HK / CN"
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={!form.name || createMutation.isPending}
                aria-busy={createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending && (
                  <LoadingSpinner label={t("common.loading")} />
                )}
                {createMutation.isPending
                  ? t("common.loading")
                  : t("common.save")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      <Card aria-busy={query.isLoading}>
        <CardContent className="pt-6">
          {query.isLoading ? (
            <TableSkeleton
              columns={3}
              rows={5}
              label={t("common.loading")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("accounts.name")}</TableHead>
                  <TableHead>{t("accounts.type")}</TableHead>
                  <TableHead>{t("accounts.country")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data ?? []).map((inst) => (
                  <TableRow key={inst.id}>
                    <TableCell className="font-medium">{inst.name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{inst.institution_type}</Badge>
                    </TableCell>
                    <TableCell>{inst.country ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function OwnersTab() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", owner_type: "individual" });

  const query = useQuery({
    queryKey: ["owners"],
    queryFn: () => api.get<Owner[]>("/api/owners"),
  });
  const createMutation = useMutation({
    mutationFn: () => api.post<Owner>("/api/owners", form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["owners"] });
      setOpen(false);
      setForm({ name: "", owner_type: "individual" });
      toast.success(t("common.saved"));
    },
    onError: () => toast.error(t("common.error")),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button>{t("accounts.add_owner")}</Button>} />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("accounts.add_owner")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t("accounts.name")}</Label>
                <Input
                  value={form.name}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, name: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("accounts.type")}</Label>
                <Select
                  value={form.owner_type}
                  onValueChange={(v) =>
                    setForm((f) => ({ ...f, owner_type: v ?? "individual" }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="individual">Individual</SelectItem>
                    <SelectItem value="family_entity">Family entity</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={!form.name || createMutation.isPending}
                aria-busy={createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending && (
                  <LoadingSpinner label={t("common.loading")} />
                )}
                {createMutation.isPending
                  ? t("common.loading")
                  : t("common.save")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      <Card aria-busy={query.isLoading}>
        <CardContent className="pt-6">
          {query.isLoading ? (
            <TableSkeleton
              columns={2}
              rows={5}
              label={t("common.loading")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("accounts.name")}</TableHead>
                  <TableHead>{t("accounts.type")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data ?? []).map((owner) => (
                  <TableRow key={owner.id}>
                    <TableCell className="font-medium">{owner.name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{owner.owner_type}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
