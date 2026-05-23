CREATE CONSTRAINT actor_id IF NOT EXISTS FOR (a:Actor) REQUIRE a.person_id IS UNIQUE;
CREATE CONSTRAINT movie_id IF NOT EXISTS FOR (m:Movie) REQUIRE m.movie_id IS UNIQUE;
CREATE INDEX actor_rank IF NOT EXISTS FOR (a:Actor) ON (a.rank);
CREATE INDEX actor_fame_rank IF NOT EXISTS FOR (a:Actor) ON (a.fame_rank);
CREATE INDEX movie_votes IF NOT EXISTS FOR (m:Movie) ON (m.vote_count);
CREATE FULLTEXT INDEX actorNames IF NOT EXISTS FOR (n:Actor) ON EACH [n.name];
CREATE FULLTEXT INDEX movieTitles IF NOT EXISTS FOR (n:Movie) ON EACH [n.title];
