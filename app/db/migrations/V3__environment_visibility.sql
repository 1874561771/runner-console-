-- 环境可见性：private=显式授权；authenticated=所有登录用户；public=游客可见
ALTER TABLE environments
    ADD COLUMN visibility ENUM('private','authenticated','public')
    NOT NULL DEFAULT 'private' AFTER disabled;
