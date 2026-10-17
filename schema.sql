-- Schéma PostgreSQL local — suivi d'entretien de piscines
create table if not exists users (
  id            serial primary key,
  email         text not null,
  name          text not null,
  password_hash text not null,
  role          text not null check (role in ('admin','client')),
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);
create unique index if not exists users_email_uq on users (lower(email));

create table if not exists pools (
  id         serial primary key,
  name       text not null,
  address    text,
  created_at timestamptz not null default now()
);

-- Quel client voit quelle piscine (un client peut en avoir plusieurs, une piscine plusieurs clients)
create table if not exists pool_access (
  user_id int not null references users(id) on delete cascade,
  pool_id int not null references pools(id) on delete cascade,
  primary key (user_id, pool_id)
);

create table if not exists pool_checks (
  id                 bigserial primary key,
  pool_id            int  not null references pools(id) on delete cascade,
  check_date         date not null,
  ph numeric, free_chlorine numeric, total_chlorine numeric, combined_chlorine numeric,
  tac numeric, th numeric, temp numeric,
  baskets boolean not null default false,
  waterline boolean not null default false,
  floor_walls boolean not null default false,
  filter_washed boolean not null default false,
  pressure numeric,
  flow_checked boolean not null default false,
  water_state text, products text, notes text,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists pool_checks_pool_date_idx on pool_checks (pool_id, check_date desc);
