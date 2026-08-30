export type WaiterUser = { id: number; username: string; role: "waiter" };

export type Connection = { baseUrl: string; token: string; expiresAt: string; user: WaiterUser };

export type OrderItem = {
  product_id: number | string;
  name?: string;
  price?: number;
  quantity: number;
  modifiers?: unknown[];
};

export type DineInSession = {
  id: string;
  table_id: string;
  table_name: string;
  status: "open" | "closed" | "cancelled";
  items: OrderItem[];
  subtotal: number;
  discount_pct: number;
  discount_amount: number;
  total: number;
  note: string;
  customer: string;
  kitchen_status: "new" | "preparing" | "ready" | "served";
  opened_by: string;
  created_at: string;
  updated_at: string;
};

export type RestaurantTable = {
  id: string;
  name: string;
  status: "free" | "busy" | "reserved";
  seats: number;
  zone: string;
  active_session?: DineInSession;
};

export type MenuProduct = { id: number | string; name: string; price: number; available?: boolean };
export type Menu = Record<string, MenuProduct[]>;
