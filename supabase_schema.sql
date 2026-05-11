create table contacts (
  id bigint generated always as identity primary key,
  name text not null unique,
  role text not null
);

create table schedules (
  id bigint generated always as identity primary key,
  date date not null,
  worker_name text not null,
  task text not null,
  status text not null default 'pending'  -- pending | done | rescheduled
);

create table tasks (
  id bigint generated always as identity primary key,
  description text not null,
  assigned_to text,
  status text not null default 'pending',  -- pending | done
  created_at timestamptz default now()
);

-- seed initial contact
insert into contacts (name, role) values ('淂溱', '顧問');
