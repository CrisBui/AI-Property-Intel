package com.propertyintel.repository.spec;

import com.propertyintel.dto.request.SearchRequest;
import com.propertyintel.entity.Listing;
import jakarta.persistence.criteria.Predicate;
import org.springframework.data.jpa.domain.Specification;

import java.util.ArrayList;
import java.util.List;


public class ListingSpecification {

    public static Specification<Listing> filterByRequest(SearchRequest request) {
        return (root, query, criteriaBuilder) -> {
            List<jakarta.persistence.criteria.Predicate> predicates = new ArrayList<>();

            // 1. Lọc theo danh sách quận (District IN (...))
            if (request.getDistricts() != null && !request.getDistricts().isEmpty()) {
                predicates.add(root.get("district").in(request.getDistricts()));
            }

            // 2. Lọc theo giá tối thiểu (priceVnd >= minPrice)
            if (request.getMinPrice() != null) {
                predicates.add(criteriaBuilder.greaterThanOrEqualTo(root.get("priceVnd"), request.getMinPrice()));
            }

            // 3. Lọc theo giá tối đa (priceVnd <= maxPrice)
            if (request.getMaxPrice() != null) {
                predicates.add(criteriaBuilder.lessThanOrEqualTo(root.get("priceVnd"), request.getMaxPrice()));
            }
            if (request.getQ() != null && !request.getQ().isBlank()) {
                String searchPattern = "%" + request.getQ().trim().toLowerCase() + "%";
                Predicate titleMatch = criteriaBuilder.like(criteriaBuilder.lower(root.get("title")), searchPattern);
                Predicate addressMatch = criteriaBuilder.like(criteriaBuilder.lower(root.get("addressText")), searchPattern);
                predicates.add(criteriaBuilder.or(titleMatch, addressMatch));
            }
            return criteriaBuilder.and(predicates.toArray(new jakarta.persistence.criteria.Predicate[0]));
        };
    }
}