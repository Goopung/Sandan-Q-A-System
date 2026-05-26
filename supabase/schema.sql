create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm;

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    attachment_key text unique not null,
    menu_no text,
    menu_name text,
    board_id text,
    post_title text,
    registered_date text,
    author text,
    detail_url text,
    attachment_name text,
    attachment_url text,
    storage_provider text default 'supabase',
    storage_bucket text,
    storage_path text,
    file_hash text,
    text_hash text,
    text_chars integer,
    rag_text_chars integer,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create table if not exists chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references documents(id) on delete cascade,
    attachment_key text not null,
    chunk_id text unique not null,
    chunk_index integer not null,
    chunk_text text not null,
    embedding vector(1536),
    menu_no text,
    menu_name text,
    board_id text,
    post_title text,
    registered_date text,
    attachment_name text,
    detail_url text,
    storage_provider text default 'supabase',
    storage_bucket text,
    storage_path text,
    text_hash text,
    created_at timestamp with time zone default now()
);

alter table documents add column if not exists storage_provider text default 'supabase';
alter table chunks add column if not exists storage_provider text default 'supabase';

create table if not exists update_runs (
    id uuid primary key default gen_random_uuid(),
    started_at timestamp with time zone default now(),
    finished_at timestamp with time zone,
    status text,
    total_documents integer default 0,
    total_chunks integer default 0,
    error_message text
);

create index if not exists documents_attachment_key_idx on documents(attachment_key);
create index if not exists documents_registered_date_idx on documents(registered_date);
create index if not exists documents_menu_name_idx on documents(menu_name);
create index if not exists documents_storage_provider_idx on documents(storage_provider);
create index if not exists chunks_attachment_key_idx on chunks(attachment_key);
create index if not exists chunks_registered_date_idx on chunks(registered_date);
create index if not exists chunks_menu_name_idx on chunks(menu_name);
create index if not exists chunks_storage_provider_idx on chunks(storage_provider);
create index if not exists chunks_text_trgm_idx on chunks using gin (chunk_text gin_trgm_ops);

-- Run this after the chunks table has at least some data for best index quality.
create index if not exists chunks_embedding_idx
on chunks
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

create or replace function match_sandan_chunks (
    query_embedding vector(1536),
    match_count int default 10,
    menu_filter text default null,
    date_from text default null,
    date_to text default null
)
returns table (
    chunk_id text,
    chunk_text text,
    similarity float,
    attachment_key text,
    menu_no text,
    menu_name text,
    board_id text,
    post_title text,
    registered_date text,
    attachment_name text,
    detail_url text,
    storage_provider text,
    storage_bucket text,
    storage_path text
)
language sql stable
as $$
    select
        chunks.chunk_id,
        chunks.chunk_text,
        1 - (chunks.embedding <=> query_embedding) as similarity,
        chunks.attachment_key,
        chunks.menu_no,
        chunks.menu_name,
        chunks.board_id,
        chunks.post_title,
        chunks.registered_date,
        chunks.attachment_name,
        chunks.detail_url,
        chunks.storage_provider,
        chunks.storage_bucket,
        chunks.storage_path
    from chunks
    where chunks.embedding is not null
      and (menu_filter is null or chunks.menu_name = menu_filter)
      and (date_from is null or chunks.registered_date >= date_from)
      and (date_to is null or chunks.registered_date <= date_to)
    order by chunks.embedding <=> query_embedding
    limit match_count;
$$;

create or replace function keyword_sandan_chunks (
    query_text text,
    match_count int default 10,
    menu_filter text default null,
    date_from text default null,
    date_to text default null
)
returns table (
    chunk_id text,
    chunk_text text,
    similarity float,
    attachment_key text,
    menu_no text,
    menu_name text,
    board_id text,
    post_title text,
    registered_date text,
    attachment_name text,
    detail_url text,
    storage_provider text,
    storage_bucket text,
    storage_path text
)
language sql stable
as $$
    select
        chunks.chunk_id,
        chunks.chunk_text,
        similarity(chunks.chunk_text, query_text) as similarity,
        chunks.attachment_key,
        chunks.menu_no,
        chunks.menu_name,
        chunks.board_id,
        chunks.post_title,
        chunks.registered_date,
        chunks.attachment_name,
        chunks.detail_url,
        chunks.storage_provider,
        chunks.storage_bucket,
        chunks.storage_path
    from chunks
    where chunks.chunk_text ilike '%' || query_text || '%'
      and (menu_filter is null or chunks.menu_name = menu_filter)
      and (date_from is null or chunks.registered_date >= date_from)
      and (date_to is null or chunks.registered_date <= date_to)
    order by similarity(chunks.chunk_text, query_text) desc
    limit match_count;
$$;
