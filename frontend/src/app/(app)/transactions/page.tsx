"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCcw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
  InlineLoading,
  LoadingSpinner,
  TableSkeleton,
} from "@/components/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { formatMoney, formatNumber } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type {
  AccountWithNames,
  Instrument,
  Transaction,
  TransactionMutationResult,
  TransactionPage,
  TransactionType,
} from "@/lib/types";

type FormType =
  | "buy"
  | "sell"
  | "deposit"
  | "withdraw"
  | "transfer"
  | "fx_exchange"
  | "dividend"
  | "interest"
  | "fee"
  | "manual_adjustment";

const FILTER_TYPES: Array<TransactionType | ""> = [
  "",
  "buy",
  "sell",
  "deposit",
  "withdraw",
  "transfer_in",
  "transfer_out",
  "fx_exchange",
  "dividend",
  "interest",
  "fee",
  "manual_adjustment",
  "valuation_update",
];

const FORM_TYPES: FormType[] = [
  "buy",
  "sell",
  "deposit",
  "withdraw",
  "transfer",
  "fx_exchange",
  "dividend",
  "interest",
  "fee",
  "manual_adjustment",
];

const today = () => new Date().toISOString().slice(0, 10);

const initialForm = {
  type: "buy" as FormType,
  account_id: "",
  to_account_id: "",
  instrument_id: "",
  quantity: "",
  price: "",
  amount: "",
  to_amount: "",
  currency: "USD",
  to_currency: "CNY",
  fee: "0",
  trade_date: today(),
  note: "",
};

export default function TransactionsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState({ account: "", type: "", instrument: "", from: "", to: "" });
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [pendingAction, setPendingAction] = useState<{ transaction: Transaction; action: "delete" | "reverse" } | null>(null);

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<AccountWithNames[]>("/api/accounts"),
  });
  const instrumentsQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const queryString = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (filters.account) params.set("account_id", filters.account);
    if (filters.type) params.set("transaction_type", filters.type);
    if (filters.instrument) params.set("instrument_id", filters.instrument);
    if (filters.from) params.set("date_from", filters.from);
    if (filters.to) params.set("date_to", filters.to);
    return params.toString();
  }, [filters]);

  const transactionsQuery = useQuery({
    queryKey: ["transactions", filters],
    queryFn: () => api.get<TransactionPage>(`/api/transactions?${queryString}`),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["instruments"] });
  };

  const createMutation = useMutation({
    mutationFn: createTransaction,
    onSuccess: () => {
      invalidate();
      setCreateOpen(false);
      setForm(initialForm);
      toast.success(zh ? "交易已记录" : "Transaction recorded");
    },
    onError: () => toast.error(zh ? "交易创建失败，请检查余额与字段" : "Could not create transaction"),
  });

  const actionMutation = useMutation({
    mutationFn: async ({ transaction, action }: NonNullable<typeof pendingAction>) => {
      if (action === "delete") return api.delete<void>(`/api/transactions/${transaction.id}`);
      return api.post<TransactionMutationResult>(`/api/transactions/${transaction.id}/reverse`);
    },
    onSuccess: () => {
      invalidate();
      setPendingAction(null);
      toast.success(zh ? "操作完成" : "Operation complete");
    },
    onError: () => toast.error(zh ? "操作失败" : "Operation failed"),
  });

  function createTransaction(): Promise<TransactionMutationResult> {
    const common = {
      account_id: form.account_id,
      currency: form.currency.toUpperCase(),
      trade_date: form.trade_date,
      note: form.note || undefined,
      source: "manual",
    };
    if (form.type === "buy" || form.type === "sell") {
      return api.post(`/api/transactions/${form.type}`, {
        ...common,
        instrument_id: form.instrument_id,
        quantity: form.quantity,
        price: form.price,
        fee: form.fee || "0",
        fee_currency: form.currency.toUpperCase(),
      });
    }
    if (form.type === "transfer") {
      return api.post("/api/transactions/transfer", {
        from_account_id: form.account_id,
        to_account_id: form.to_account_id,
        instrument_id: form.instrument_id,
        quantity: form.quantity,
        currency: form.currency.toUpperCase(),
        trade_date: form.trade_date,
        note: form.note || undefined,
        source: "manual",
      });
    }
    if (form.type === "fx_exchange") {
      return api.post("/api/transactions/fx-exchange", {
        account_id: form.account_id,
        from_currency: form.currency.toUpperCase(),
        from_amount: form.amount,
        to_currency: form.to_currency.toUpperCase(),
        to_amount: form.to_amount,
        fee: form.fee || "0",
        fee_currency: form.currency.toUpperCase(),
        trade_date: form.trade_date,
        note: form.note || undefined,
        source: "manual",
      });
    }
    if (form.type === "dividend" || form.type === "interest") {
      return api.post("/api/transactions/income", {
        ...common,
        instrument_id: form.instrument_id || undefined,
        amount: form.amount,
        transaction_type: form.type,
      });
    }
    if (form.type === "fee") {
      return api.post("/api/transactions/fee", {
        ...common,
        instrument_id: form.instrument_id || undefined,
        amount: form.amount,
      });
    }
    if (form.type === "manual_adjustment") {
      return api.post("/api/transactions/adjustment", {
        account_id: form.account_id,
        instrument_id: form.instrument_id,
        delta_quantity: form.quantity,
        currency: form.currency.toUpperCase(),
        trade_date: form.trade_date,
        note: form.note || undefined,
        source: "manual",
      });
    }
    return api.post("/api/transactions/cash", {
      ...common,
      amount: form.amount,
      transaction_type: form.type,
    });
  }

  const rows = transactionsQuery.data?.items ?? [];
  const summaryCurrency = rows[0]?.currency ?? "USD";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{zh ? "交易账本" : "Transaction Ledger"}</h1>
          <p className="text-sm text-muted-foreground">{zh ? "所有交易与持仓变化保持同步" : "Transactions and current holdings stay in sync"}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" /> {zh ? "新建交易" : "New transaction"}
        </Button>
      </div>

      <Card>
        <CardContent className="grid gap-3 pt-6 sm:grid-cols-2 lg:grid-cols-5">
          <NativeSelect value={filters.account} onChange={(value) => setFilters((old) => ({ ...old, account: value }))}>
            <option value="">{zh ? "全部账户" : "All accounts"}</option>
            {(accountsQuery.data ?? []).map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </NativeSelect>
          <NativeSelect value={filters.type} onChange={(value) => setFilters((old) => ({ ...old, type: value }))}>
            {FILTER_TYPES.map((type) => <option key={type || "all"} value={type}>{type ? typeLabel(type, zh) : zh ? "全部类型" : "All types"}</option>)}
          </NativeSelect>
          <NativeSelect value={filters.instrument} onChange={(value) => setFilters((old) => ({ ...old, instrument: value }))}>
            <option value="">{zh ? "全部资产" : "All instruments"}</option>
            {(instrumentsQuery.data ?? []).map((instrument) => <option key={instrument.id} value={instrument.id}>{instrument.symbol || instrument.name}</option>)}
          </NativeSelect>
          <Input type="date" value={filters.from} onChange={(event) => setFilters((old) => ({ ...old, from: event.target.value }))} aria-label={zh ? "开始日期" : "Start date"} />
          <Input type="date" value={filters.to} onChange={(event) => setFilters((old) => ({ ...old, to: event.target.value }))} aria-label={zh ? "结束日期" : "End date"} />
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-3">
        <Summary label={zh ? "总买入" : "Total buys"} value={formatMoney(transactionsQuery.data?.summary.total_buy ?? 0, summaryCurrency)} />
        <Summary label={zh ? "总卖出" : "Total sells"} value={formatMoney(transactionsQuery.data?.summary.total_sell ?? 0, summaryCurrency)} />
        <Summary label={zh ? "净现金流（名义）" : "Net cash flow (nominal)"} value={formatMoney(transactionsQuery.data?.summary.net_cash_flow ?? 0, summaryCurrency)} />
      </div>

      {transactionsQuery.isFetching && !transactionsQuery.isLoading && (
        <InlineLoading
          label={zh ? "正在更新筛选结果…" : "Updating filtered results…"}
          className="border-primary/20 bg-primary/5 text-foreground"
        />
      )}

      <Card aria-busy={transactionsQuery.isFetching}>
        <CardContent className="overflow-x-auto pt-6">
          {transactionsQuery.isLoading ? (
            <TableSkeleton
              columns={10}
              rows={8}
              label={zh ? "正在加载交易记录" : "Loading transactions"}
              className="min-w-[900px]"
            />
          ) : (
            <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{zh ? "日期" : "Date"}</TableHead><TableHead>{zh ? "账户" : "Account"}</TableHead>
                <TableHead>{zh ? "类型" : "Type"}</TableHead><TableHead>{zh ? "资产" : "Instrument"}</TableHead>
                <TableHead className="text-right">{zh ? "数量" : "Quantity"}</TableHead><TableHead className="text-right">{zh ? "价格" : "Price"}</TableHead>
                <TableHead className="text-right">{zh ? "金额" : "Amount"}</TableHead><TableHead>{zh ? "手续费" : "Fee"}</TableHead>
                <TableHead>{zh ? "备注 / 来源" : "Note / Source"}</TableHead><TableHead className="text-right">{zh ? "操作" : "Actions"}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((transaction) => (
                <TableRow key={transaction.id} className={transaction.is_reversed ? "opacity-50" : undefined}>
                  <TableCell>
                    <div>{transaction.trade_date}</div>
                    {transaction.executed_at && <div className="text-xs text-muted-foreground">{new Date(transaction.executed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZoneName: "short" })}</div>}
                  </TableCell>
                  <TableCell>{transaction.account_name}</TableCell>
                  <TableCell><Badge variant="outline">{typeLabel(transaction.transaction_type, zh)}</Badge>{transaction.is_reversed && <Badge variant="secondary" className="ml-1">{zh ? "已冲销" : "Reversed"}</Badge>}</TableCell>
                  <TableCell>{transaction.instrument_symbol || transaction.instrument_name || "-"}</TableCell>
                  <TableCell className="text-right">{formatNumber(transaction.quantity)}</TableCell>
                  <TableCell className="text-right">{transaction.price ? formatMoney(transaction.price, transaction.currency) : "-"}</TableCell>
                  <TableCell className="text-right">{formatMoney(transaction.amount, transaction.currency)}</TableCell>
                  <TableCell>{Number(transaction.fee) ? `${formatNumber(transaction.fee)} ${transaction.fee_currency}` : "-"}</TableCell>
                  <TableCell className="max-w-48 truncate text-muted-foreground" title={transaction.note ?? undefined}>{transaction.note || "-"} · {transaction.source}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon-sm" disabled={transaction.is_reversed} onClick={() => setPendingAction({ transaction, action: "reverse" })} title={zh ? "冲销" : "Reverse"}><RotateCcw className="h-4 w-4" /></Button>
                      <Button variant="ghost" size="icon-sm" disabled={transaction.is_reversed || transaction.external_ref?.startsWith("reversal:")} onClick={() => setPendingAction({ transaction, action: "delete" })} title={zh ? "删除" : "Delete"}><Trash2 className="h-4 w-4" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {!transactionsQuery.isLoading && rows.length === 0 && <TableRow><TableCell colSpan={10} className="py-10 text-center text-muted-foreground">{zh ? "暂无交易" : "No transactions"}</TableCell></TableRow>}
            </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{zh ? "新建交易" : "New transaction"}</DialogTitle><DialogDescription>{zh ? "保存后会原子性更新账本、资产持仓和现金。" : "Saving atomically updates the ledger, holdings, and cash."}</DialogDescription></DialogHeader>
          <TransactionForm form={form} setForm={setForm} accounts={accountsQuery.data ?? []} instruments={instrumentsQuery.data ?? []} zh={zh} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>{zh ? "取消" : "Cancel"}</Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
              aria-busy={createMutation.isPending}
            >
              {createMutation.isPending && (
                <LoadingSpinner label={zh ? "保存中" : "Saving"} />
              )}
              {createMutation.isPending
                ? zh
                  ? "保存中…"
                  : "Saving…"
                : zh
                  ? "保存"
                  : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(pendingAction)} onOpenChange={(open) => !open && setPendingAction(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{pendingAction?.action === "delete" ? (zh ? "删除交易？" : "Delete transaction?") : (zh ? "冲销交易？" : "Reverse transaction?")}</DialogTitle><DialogDescription>{pendingAction?.action === "delete" ? (zh ? "交易记录会被物理删除，相关持仓将回滚。" : "The row will be deleted and holding effects rolled back.") : (zh ? "系统会创建反向交易并保留完整审计记录。" : "Inverse entries will be created and the audit trail retained.")}</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setPendingAction(null)}>{zh ? "取消" : "Cancel"}</Button><Button variant={pendingAction?.action === "delete" ? "destructive" : "default"} onClick={() => pendingAction && actionMutation.mutate(pendingAction)} disabled={actionMutation.isPending} aria-busy={actionMutation.isPending}>{actionMutation.isPending && <LoadingSpinner label={zh ? "执行中" : "Applying action"} />}{actionMutation.isPending ? (zh ? "执行中…" : "Applying…") : (zh ? "确认" : "Confirm")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function TransactionForm({ form, setForm, accounts, instruments, zh }: { form: typeof initialForm; setForm: React.Dispatch<React.SetStateAction<typeof initialForm>>; accounts: AccountWithNames[]; instruments: Instrument[]; zh: boolean }) {
  const update = (key: keyof typeof form, value: string) => setForm((old) => ({ ...old, [key]: value }));
  const needsInstrument = ["buy", "sell", "transfer", "manual_adjustment"].includes(form.type);
  const needsAmount = ["deposit", "withdraw", "dividend", "interest", "fee", "fx_exchange"].includes(form.type);
  return <div className="grid gap-4 sm:grid-cols-2">
    <Field label={zh ? "类型" : "Type"}><NativeSelect value={form.type} onChange={(value) => update("type", value as FormType)}>{FORM_TYPES.map((type) => <option key={type} value={type}>{typeLabel(type, zh)}</option>)}</NativeSelect></Field>
    <Field label={form.type === "transfer" ? (zh ? "转出账户" : "From account") : (zh ? "账户" : "Account")}><NativeSelect value={form.account_id} onChange={(value) => update("account_id", value)}><option value="">{zh ? "请选择" : "Select"}</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</NativeSelect></Field>
    {form.type === "transfer" && <Field label={zh ? "转入账户" : "To account"}><NativeSelect value={form.to_account_id} onChange={(value) => update("to_account_id", value)}><option value="">{zh ? "请选择" : "Select"}</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</NativeSelect></Field>}
    {(needsInstrument || ["dividend", "interest", "fee"].includes(form.type)) && <Field label={zh ? "资产" : "Instrument"}><NativeSelect value={form.instrument_id} onChange={(value) => update("instrument_id", value)}><option value="">{needsInstrument ? (zh ? "请选择" : "Select") : (zh ? "可选" : "Optional")}</option>{instruments.map((instrument) => <option key={instrument.id} value={instrument.id}>{instrument.symbol ? `${instrument.symbol} · ` : ""}{instrument.name}</option>)}</NativeSelect></Field>}
    {["buy", "sell", "transfer", "manual_adjustment"].includes(form.type) && <Field label={form.type === "manual_adjustment" ? (zh ? "数量变化（可为负）" : "Quantity delta") : (zh ? "数量" : "Quantity")}><Input type="number" step="any" value={form.quantity} onChange={(event) => update("quantity", event.target.value)} /></Field>}
    {["buy", "sell"].includes(form.type) && <Field label={zh ? "单价" : "Price"}><Input type="number" min="0" step="any" value={form.price} onChange={(event) => update("price", event.target.value)} /></Field>}
    {needsAmount && <Field label={form.type === "fx_exchange" ? (zh ? "卖出金额" : "From amount") : (zh ? "金额" : "Amount")}><Input type="number" min="0" step="any" value={form.amount} onChange={(event) => update("amount", event.target.value)} /></Field>}
    <Field label={form.type === "fx_exchange" ? (zh ? "卖出币种" : "From currency") : (zh ? "币种" : "Currency")}><Input value={form.currency} maxLength={3} onChange={(event) => update("currency", event.target.value.toUpperCase())} /></Field>
    {form.type === "fx_exchange" && <><Field label={zh ? "买入金额" : "To amount"}><Input type="number" min="0" step="any" value={form.to_amount} onChange={(event) => update("to_amount", event.target.value)} /></Field><Field label={zh ? "买入币种" : "To currency"}><Input value={form.to_currency} maxLength={3} onChange={(event) => update("to_currency", event.target.value.toUpperCase())} /></Field></>}
    {["buy", "sell", "fx_exchange"].includes(form.type) && <Field label={zh ? "手续费" : "Fee"}><Input type="number" min="0" step="any" value={form.fee} onChange={(event) => update("fee", event.target.value)} /></Field>}
    <Field label={zh ? "交易日期" : "Trade date"}><Input type="date" value={form.trade_date} onChange={(event) => update("trade_date", event.target.value)} /></Field>
    <div className="sm:col-span-2"><Field label={zh ? "备注" : "Note"}><Textarea value={form.note} onChange={(event) => update("note", event.target.value)} /></Field></div>
  </div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <div className="space-y-1.5"><Label>{label}</Label>{children}</div>; }
function NativeSelect({ value, onChange, children }: { value: string; onChange: (value: string) => void; children: React.ReactNode }) { return <select value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/40">{children}</select>; }
function Summary({ label, value }: { label: string; value: string }) { return <Card><CardContent className="pt-6"><div className="text-sm text-muted-foreground">{label}</div><div className="mt-1 text-xl font-semibold">{value}</div></CardContent></Card>; }
function typeLabel(type: string, zh: boolean) { const labels: Record<string, [string, string]> = { buy: ["买入", "Buy"], sell: ["卖出", "Sell"], deposit: ["存入", "Deposit"], withdraw: ["取出", "Withdraw"], transfer: ["内部转账", "Transfer"], transfer_in: ["转入", "Transfer in"], transfer_out: ["转出", "Transfer out"], fx_exchange: ["换汇", "FX exchange"], dividend: ["分红", "Dividend"], interest: ["利息", "Interest"], fee: ["手续费", "Fee"], manual_adjustment: ["人工调整", "Manual adjustment"], valuation_update: ["估值更新", "Valuation update"] }; return labels[type]?.[zh ? 0 : 1] ?? type; }
